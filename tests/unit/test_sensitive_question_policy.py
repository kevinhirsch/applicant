"""P2-7 — the sensitive-question policy, pinned server-side.

THE CLAIM: **protected questions are never answered by AI.** Two question
classes are protected (FR-ATTR-6, NFR-PRIV-1, P2-7):

* **Demographic / EEO self-identification** — answered only from the user's
  explicit stored answer, else the canned decline. Never guessed, never
  leaked into the reusable answer library.
* **Work authorization / visa / sponsorship** — answered only in the user's
  OWN words (an explicit answer, their onboarding intake, or their stored
  attributes), else an honest needs-your-answer placeholder. Never guessed:
  an invented "No, I don't need sponsorship" contains no fact-class tokens,
  so the fabrication guard alone could not catch it — the refusal happens at
  classification time, in BOTH lanes (screening-answer generation AND the
  pre-fill field resolver).

Enforcement is server-side: a caller's ``essay`` flag cannot opt a protected
question back into the LLM path. The tests wire an LLM stub that fails the
test if it is ever consulted — the strongest form of "never guessed".

Reproduce:
    DATABASE_URL='postgresql+psycopg://x:x@127.0.0.1:1/none' \
      uv run pytest -q tests/unit/test_sensitive_question_policy.py
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from applicant.adapters.browser.patchright_browser import PatchrightBrowser
from applicant.adapters.detection.detection_monitor import DetectionMonitor
from applicant.adapters.resume_tailoring.latex_tailor import LatexTailor
from applicant.adapters.sandbox.local_sandbox import LocalSandbox
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.material_service import MaterialService
from applicant.application.services.prefill_service import PrefillService
from applicant.core.entities.attribute import Attribute
from applicant.core.entities.onboarding_profile import OnboardingProfile
from applicant.core.ids import (
    ApplicationId,
    AttributeId,
    CampaignId,
    OnboardingProfileId,
    new_id,
)
from applicant.core.rules.materials import ScreeningKind, classify_screening_question
from applicant.core.rules.sensitive_fields import (
    DECLINE_TO_SELF_IDENTIFY,
    is_work_auth_question,
)
from applicant.ports.driven.browser_automation import DetectedField


class _MustNotBeConsulted:
    """An LLM stand-in that fails the test on ANY consultation."""

    def complete(self, *args, **kwargs):  # pragma: no cover - the point is it never runs
        raise AssertionError("the LLM must never be consulted for a protected question")


@pytest.fixture
def storage() -> InMemoryStorage:
    return InMemoryStorage()


@pytest.fixture
def svc(storage) -> MaterialService:
    """MaterialService whose LLM EXPLODES if consulted — every generation in
    these tests must be policy-driven, not generated."""
    return MaterialService(
        storage, llm=_MustNotBeConsulted(), resume_tailoring=LatexTailor()
    )


def _cid() -> CampaignId:
    return CampaignId(new_id())


def _aid() -> ApplicationId:
    return ApplicationId(new_id())


def _intake(storage, cid, work_auth: dict) -> None:
    storage.onboarding_profiles.add(
        OnboardingProfile(
            id=OnboardingProfileId(new_id()),
            campaign_id=cid,
            completion_flag=True,
            intake={"work_authorization": work_auth},
        )
    )
    storage.commit()


def _attr(storage, cid, name, value) -> None:
    storage.attributes.add(
        Attribute(id=AttributeId(new_id()), campaign_id=cid, name=name, value=value)
    )
    storage.commit()


def _policy_kinds(doc) -> list[str]:
    return [p.ref for p in doc.provenance if p.kind == MaterialService.POLICY_PROVENANCE_KIND]


# ── classification: the protected lane catches real-world phrasings ─────────


@pytest.mark.unit
@pytest.mark.parametrize(
    "question",
    [
        # The classic long-form ATS phrasing — 13 words, so any word-count
        # heuristic alone would have missed it.
        "Will you now or in the future require sponsorship for employment visa status?",
        "Are you legally authorized to work in the United States?",
        # An essay cue ("describe your") must NOT pull this into the LLM lane.
        "Describe your work authorization status",
        # Bare field labels / short closed questions (the weak markers).
        "Visa status",
        "Are you a citizen?",
        "Do you need sponsorship?",
        "What is your citizenship status?",
        "Do you have a work permit?",
    ],
)
def test_work_auth_phrasings_classify_work_auth(question):
    assert classify_screening_question(question) is ScreeningKind.WORK_AUTH
    assert is_work_auth_question(question)


@pytest.mark.unit
@pytest.mark.parametrize(
    "question",
    [
        # Long essay prompts that merely MENTION a weak marker stay essays —
        # the weak markers only fire on short field-label-shaped questions.
        "Tell us about a time you helped a customer with visa processing delays",
        "Describe your volunteering work with senior citizens in your community",
    ],
)
def test_essays_mentioning_visa_or_citizens_stay_essays(question):
    assert classify_screening_question(question) is ScreeningKind.ESSAY


@pytest.mark.unit
def test_eeo_and_diversity_classification_is_unchanged():
    """The work-auth lane must not disturb the existing EEO split."""
    assert classify_screening_question("What is your race/ethnicity?") is ScreeningKind.SENSITIVE
    assert (
        classify_screening_question("How do you foster gender diversity on a team?")
        is ScreeningKind.ESSAY
    )


# ── the caller cannot opt a protected question back into the LLM lane ───────


@pytest.mark.unit
def test_the_essay_flag_cannot_force_a_work_auth_question_to_the_llm(svc, storage):
    """Server-side enforcement: essay=True on a work-auth question is ignored.
    The exploding-LLM fixture proves no generation happened."""
    doc = svc.generate_screening_answer(
        _cid(), _aid(), "Do you require sponsorship? yes/no", "irrelevant", essay=True
    )
    assert doc.content == MaterialService._WORK_AUTH_NEEDS_ANSWER
    assert _policy_kinds(doc) == ["policy:work_auth"]


@pytest.mark.unit
def test_the_essay_flag_cannot_force_an_eeo_question_to_the_llm(svc):
    doc = svc.generate_screening_answer(
        _cid(), _aid(), "What is your race/ethnicity?", "irrelevant", essay=True
    )
    assert doc.content == DECLINE_TO_SELF_IDENTIFY
    assert _policy_kinds(doc) == ["policy:sensitive"]


# ── work-auth answers: the user's own words, or an honest deferral ──────────


@pytest.mark.unit
def test_no_stored_answer_defers_honestly_and_never_says_no(svc):
    """The dangerous failure mode: with NOTHING stored, the engine must not
    answer a sponsorship question either way — it defers, and says so."""
    doc = svc.generate_screening_answer(
        _cid(), _aid(), "Do you require sponsorship?", "resume text", essay=None
    )
    assert doc.content == MaterialService._WORK_AUTH_NEEDS_ANSWER
    assert _policy_kinds(doc) == ["policy:work_auth"]


@pytest.mark.unit
def test_a_stored_intake_no_is_answered_in_a_full_sentence(svc, storage):
    cid = _cid()
    _intake(storage, cid, {"needs_sponsorship": False})
    doc = svc.generate_screening_answer(
        cid, _aid(), "Will you now or in the future require sponsorship for employment visa status?",
        "resume text", essay=None,
    )
    assert doc.content == "No, I do not require sponsorship for employment."
    assert _policy_kinds(doc) == ["policy:work_auth"]


@pytest.mark.unit
def test_a_stored_intake_yes_is_answered_yes(svc, storage):
    cid = _cid()
    _intake(storage, cid, {"needs_sponsorship": True})
    doc = svc.generate_screening_answer(
        cid, _aid(), "Do you require sponsorship?", "resume text", essay=None
    )
    assert doc.content == "Yes, I will require sponsorship for employment."


@pytest.mark.unit
def test_an_absent_intake_key_is_not_treated_as_no(svc, storage):
    """PRESENCE-aware: an intake that exists but never answered the sponsorship
    question must defer — absence is not 'no' when answering a legal question."""
    cid = _cid()
    _intake(storage, cid, {"status": ""})  # intake exists; sponsorship unanswered
    doc = svc.generate_screening_answer(
        cid, _aid(), "Do you require sponsorship?", "resume text", essay=None
    )
    assert doc.content == MaterialService._WORK_AUTH_NEEDS_ANSWER


@pytest.mark.unit
def test_a_stored_status_string_is_used_verbatim_with_no_inference(svc, storage):
    """The engine answers with the user's own words — it never converts a
    status into a yes/no on their behalf."""
    cid = _cid()
    _intake(storage, cid, {"status": "US Citizen"})
    doc = svc.generate_screening_answer(
        cid, _aid(), "Are you authorized to work in the United States?",
        "resume text", essay=None,
    )
    assert doc.content == "US Citizen"


@pytest.mark.unit
def test_the_attribute_cloud_fallback_answers_verbatim(svc, storage):
    """The missing-detail flow stores the user's typed answer as an attribute;
    the next work-auth question uses those words."""
    cid = _cid()
    _attr(storage, cid, "work authorization", "Authorized to work; TN visa")
    doc = svc.generate_screening_answer(
        cid, _aid(), "What is your work authorization status?", "resume text", essay=None
    )
    assert doc.content == "Authorized to work; TN visa"


@pytest.mark.unit
def test_an_explicit_answer_wins_and_is_saved_for_reuse(svc, storage):
    cid = _cid()
    doc = svc.generate_screening_answer(
        cid, _aid(), "Are you authorized to work in the US?", "resume text",
        essay=None, explicit_answer="Yes, US citizen",
    )
    assert doc.content == "Yes, US citizen"
    assert _policy_kinds(doc) == ["policy:work_auth"]
    items = svc.list_screening_answer_library(cid)
    assert [i["answer"] for i in items] == ["Yes, US citizen"]


@pytest.mark.unit
def test_the_needs_answer_placeholder_never_enters_the_answer_library(svc):
    """The placeholder is not an answer; reusing it on a future application
    would silently underdeliver."""
    cid = _cid()
    svc.generate_screening_answer(
        cid, _aid(), "Do you require sponsorship?", "resume text", essay=None
    )
    assert svc.list_screening_answer_library(cid) == []


@pytest.mark.unit
def test_sensitive_answers_still_never_enter_the_answer_library(svc):
    """Unchanged by P2-7, re-pinned beside it: EEO answers (even explicit ones)
    never leak into the cross-application store."""
    cid = _cid()
    svc.generate_screening_answer(
        cid, _aid(), "What is your gender?", "resume text",
        essay=None, explicit_answer="Prefer not to say",
    )
    assert svc.list_screening_answer_library(cid) == []


# ── review transparency: the policy marker reaches the review surface ───────


@pytest.mark.unit
def test_policy_provenance_distinguishes_stored_from_needed(svc, storage):
    cid = _cid()
    _intake(storage, cid, {"needs_sponsorship": False})
    answered = svc.generate_screening_answer(
        cid, _aid(), "Do you require sponsorship?", "resume text", essay=None
    )
    deferred = svc.generate_screening_answer(
        _cid(), _aid(), "Do you require sponsorship?", "resume text", essay=None
    )
    answered_labels = [p.label for p in answered.provenance]
    deferred_labels = [p.label for p in deferred.provenance]
    assert any("your own stored answer" in lbl for lbl in answered_labels)
    assert any("only you can answer" in lbl for lbl in deferred_labels)


@pytest.mark.unit
def test_sensitive_policy_provenance_distinguishes_explicit_from_declined(svc):
    explicit = svc.generate_screening_answer(
        _cid(), _aid(), "What is your gender?", "resume text",
        essay=None, explicit_answer="Prefer not to say",
    )
    declined = svc.generate_screening_answer(
        _cid(), _aid(), "What is your gender?", "resume text", essay=None
    )
    assert any("your stored answer" in p.label for p in explicit.provenance)
    assert any("declining to self-identify" in p.label for p in declined.provenance)


@pytest.mark.unit
def test_policy_markers_flow_through_the_review_api_payload(svc):
    """Reachability: the documents router serializes policy provenance for the
    review UI's "What I drew on" panel (unlike the degraded sentinel, which is
    deliberately excluded there)."""
    from applicant.app.routers.documents import _provenance_payload

    doc = svc.generate_screening_answer(
        _cid(), _aid(), "Do you require sponsorship?", "resume text", essay=None
    )
    payload = _provenance_payload(doc.provenance)
    assert payload and payload[0]["kind"] == "policy"
    assert "work-authorization" in payload[0]["label"].lower()


# ── the pre-fill lane: the SAME policy, enforced at field resolution ─────────


def _prefill(storage, llm) -> PrefillService:
    return PrefillService(
        storage=storage,
        browser=PatchrightBrowser(),
        detection=DetectionMonitor(),
        sandbox=LocalSandbox(),
        credentials=None,
        llm=llm,
    )


def _field(label, field_type="text") -> DetectedField:
    return DetectedField(selector="#f", label=label, field_type=field_type, required=True)


@pytest.mark.unit
@pytest.mark.parametrize(
    "label,field_type",
    [
        ("Will you now or in the future require sponsorship for employment visa status?", "text"),
        ("Describe your work authorization", "textarea"),
        ("Visa status", "text"),
    ],
)
def test_prefill_never_drafts_a_work_auth_field(storage, label, field_type):
    """With NOTHING stored, a work-auth field resolves to None (→ ask the user)
    and the LLM is never consulted — even for a textarea, which is otherwise
    always draftable."""
    svc = _prefill(storage, _MustNotBeConsulted())
    from applicant.application.services.prefill_service import PrefillResult

    resolved = svc._resolve_value(
        _field(label, field_type), [], PrefillResult(application_id=_aid(), state=None)
    )
    assert resolved.value is None
    assert resolved.generated is False


@pytest.mark.unit
def test_prefill_generate_screening_answer_refuses_work_auth_directly(storage):
    """Defence in depth: the drafting helper itself refuses, even if a future
    caller forgets the classification check."""
    svc = _prefill(storage, _MustNotBeConsulted())
    cid = _cid()
    attrs = [
        Attribute(
            id=AttributeId(new_id()), campaign_id=cid,
            name="Python experience", value="8 years",
        )
    ]
    assert svc._generate_screening_answer(_field("Do you need a visa?"), attrs) is None


@pytest.mark.unit
def test_prefill_still_drafts_ordinary_screening_questions(storage):
    """Positive control: the guard is specific — a normal screening question
    still reaches the LLM draft path, so the refusal above is the policy, not a
    broken harness."""
    stub = SimpleNamespace(
        complete=lambda *a, **k: SimpleNamespace(text="8 years", low_confidence=False)
    )
    svc = _prefill(storage, stub)
    cid = _cid()
    attrs = [
        Attribute(
            id=AttributeId(new_id()), campaign_id=cid,
            name="Python experience", value="8 years",
        )
    ]
    drafted = svc._generate_screening_answer(
        _field("How many years of Python experience do you have?"), attrs
    )
    assert drafted is not None


@pytest.mark.unit
def test_prefill_fills_work_auth_from_the_users_stored_attribute(storage):
    """The stored-answer path stays open: an attribute matching the field label
    fills with the user's own words (no LLM involved)."""
    svc = _prefill(storage, _MustNotBeConsulted())
    from applicant.application.services.prefill_service import PrefillResult

    cid = _cid()
    attrs = [
        Attribute(
            id=AttributeId(new_id()), campaign_id=cid,
            name="Are you authorized to work?", value="Yes",
        )
    ]
    resolved = svc._resolve_value(
        _field("Are you authorized to work?"),
        attrs,
        PrefillResult(application_id=_aid(), state=None),
    )
    assert resolved.value == "Yes"
