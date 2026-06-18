"""Unit tests for MaterialService deepening (Phase 3 part A).

Covers the variant library + selection/generation + lineage + cluster/cap
(FR-RESUME-6/7), the truthfulness fabrication guardrail wired into generation +
revision (FR-RESUME-2, NFR-TRUTH-1), the non-AI-looking filters (em-dash + UI
banned list + voice) on every pass (FR-RESUME-5), and engine selection respecting
the Phase 0 ConversionService choice (FR-RESUME-3a).
"""

from __future__ import annotations

import pytest

from applicant.adapters.embedding.local_embedding import LocalEmbedding
from applicant.adapters.resume_tailoring.docx_tailor import DocxTailor
from applicant.adapters.resume_tailoring.latex_tailor import LatexTailor
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.conversion_service import ConversionService
from applicant.application.services.material_service import VARIANT_CAP, MaterialService
from applicant.core.entities.resume_variant import ResumeVariant
from applicant.core.errors import TruthfulnessViolation
from applicant.core.ids import ApplicationId, CampaignId, JobPostingId, ResumeVariantId, new_id

BASE = (
    "\\section{Skills}\n"
    "Python developer who built data pipelines.\n"
    "Wrote SQL for analytics dashboards.\n"
)


@pytest.fixture
def storage() -> InMemoryStorage:
    return InMemoryStorage()


@pytest.fixture
def svc(storage) -> MaterialService:
    return MaterialService(
        storage, llm=None, resume_tailoring=LatexTailor(), embedding=LocalEmbedding()
    )


def _add_variant(storage, cid, *, approved=True, sig="Python", parent=None) -> ResumeVariant:
    v = ResumeVariant(
        id=ResumeVariantId(new_id()),
        campaign_id=cid,
        storage_path=f"variants/{new_id()}.tex",
        parent_id=parent,
        targeted_jd_signature=sig,
        approved=approved,
    )
    storage.resume_variants.add(v)
    storage.commit()
    return v


# === selection/generation + lineage (FR-RESUME-6/7) =======================
@pytest.mark.unit
def test_reuse_when_approved_variant_clears_threshold(svc, storage):
    cid = CampaignId(new_id())
    _add_variant(storage, cid, sig="Python,SQL")
    # JD fully covered by the base source -> reuse, not generate.
    sel = svc.select_or_generate(cid, JobPostingId(new_id()), ["Python", "SQL"], BASE)
    assert sel.generated is False
    assert sel.fit.coverage * 100 >= 70


@pytest.mark.unit
def test_generate_with_lineage_when_all_below_threshold(svc, storage):
    cid = CampaignId(new_id())
    parent = _add_variant(storage, cid, sig="Python")
    sel = svc.select_or_generate(
        cid, JobPostingId(new_id()), ["Python", "Kubernetes", "Terraform"], BASE
    )
    assert sel.generated is True
    assert sel.variant.parent_id == parent.id  # best parent chosen (FR-RESUME-6)
    assert sel.variant.approved is False  # must pass review first


@pytest.mark.unit
def test_only_approved_variants_are_reusable_parents(svc, storage):
    cid = CampaignId(new_id())
    _add_variant(storage, cid, approved=False, sig="Python,SQL")  # unapproved -> ignored
    sel = svc.select_or_generate(cid, JobPostingId(new_id()), ["Python", "SQL"], BASE)
    assert sel.generated is True
    assert sel.variant.parent_id is None  # no approved parent existed


@pytest.mark.unit
def test_lineage_walks_to_root(svc, storage):
    cid = CampaignId(new_id())
    root = _add_variant(storage, cid, sig="root")
    child = _add_variant(storage, cid, sig="child", parent=root.id)
    grandchild = _add_variant(storage, cid, sig="gc", parent=child.id)
    chain = svc.lineage(grandchild)
    assert [v.id for v in chain] == [grandchild.id, child.id, root.id]


@pytest.mark.unit
def test_approve_variant_makes_it_reusable(svc, storage):
    cid = CampaignId(new_id())
    v = _add_variant(storage, cid, approved=False, sig="Python,SQL")
    approved = svc.approve_variant(v.id)
    assert approved.approved is True
    reused = svc.select_or_generate(cid, JobPostingId(new_id()), ["Python", "SQL"], BASE)
    assert reused.generated is False


# === converting-signature bias on variant selection (FR-LEARN-5) ==========
@pytest.mark.unit
def test_variant_selection_prefers_converting_signature(storage):
    # FR-LEARN-5: with a recorded conversion signature, selection prefers the
    # approved variant whose traits match the converting role (a tiebreak over
    # equal-coverage candidates). Without learning, the choice would be arbitrary.
    from applicant.application.services.learning_service import LearningService

    cid = CampaignId(new_id())
    learning = LearningService(storage, LocalEmbedding())
    model = learning.load_model(cid)
    model = learning.record_converting_role(
        model, "python backend distributed systems kubernetes platform"
    )
    learning.persist_model(model)

    # Two approved variants that BOTH cover the JD (same base source → equal
    # coverage), but with different targeted-JD signatures.
    aligned = _add_variant(
        storage, cid, sig="python,backend,kubernetes,distributed,platform"
    )
    off = _add_variant(storage, cid, sig="frontend,react,css,design")

    svc = MaterialService(
        storage,
        llm=None,
        resume_tailoring=LatexTailor(),
        embedding=LocalEmbedding(),
        learning=learning,
    )
    sel = svc.select_or_generate(cid, JobPostingId(new_id()), ["Python", "SQL"], BASE)
    assert sel.generated is False
    assert sel.variant.id == aligned.id
    assert off.id != aligned.id  # sanity: distinct candidates existed


# === cluster/cap (FR-RESUME-6) ============================================
@pytest.mark.unit
def test_cluster_collapses_identical_signatures(svc, storage):
    cid = CampaignId(new_id())
    _add_variant(storage, cid, sig="Python,SQL")
    _add_variant(storage, cid, sig="Python,SQL")  # exact duplicate
    kept = svc.cluster_and_cap(cid)
    assert len(kept) == 1  # one representative survives the cluster


@pytest.mark.unit
def test_cap_limits_library_sprawl(svc, storage):
    cid = CampaignId(new_id())
    for i in range(VARIANT_CAP + 3):
        _add_variant(storage, cid, sig=f"role-{i}")
    kept = svc.cluster_and_cap(cid)
    assert len(kept) <= VARIANT_CAP
    approved = [v for v in storage.resume_variants.list_for_campaign(cid) if v.approved]
    assert len(approved) <= VARIANT_CAP


# === truthfulness on generation + revision (FR-RESUME-2) ==================
@pytest.mark.unit
def test_fabrication_rejected_on_generation(svc):
    with pytest.raises(TruthfulnessViolation):
        svc.assert_no_fabrication("Python and SQL.", "Expert in Kubernetes.")


# === #17: LLM-injected fabrication on select_or_generate is gated ==========
class _FabricatingLLM:
    """An LLM that injects an unsupported skill into the generated variant body."""

    def is_configured(self) -> bool:
        return True

    def complete(self, messages, **kwargs):
        from applicant.ports.driven.llm import LLMResult

        # The model adds a skill the candidate never had (a fabrication).
        return LLMResult(
            text="Seasoned expert in Kubernetes and Rust.", tier=1, model="fake"
        )


class _StartTierRecordingLLM:
    """Records the start_tier each generation pass requested."""

    def __init__(self) -> None:
        self.start_tiers: list[int] = []

    def is_configured(self) -> bool:
        return True

    def complete(self, messages, **kwargs):
        from applicant.ports.driven.llm import LLMResult

        self.start_tiers.append(kwargs.get("start_tier", 1))
        # Echo a grounded body so the truthfulness gate passes.
        return LLMResult(text="Python and SQL work.", tier=2, model="fake")


@pytest.mark.unit
def test_strip_llm_preamble_removes_meta_only():
    from applicant.application.services.material_service import _strip_llm_preamble

    # Strips the model's "Here's a draft…:" / "Sure, here is the revised version:" lead.
    pre = (
        "Here's a cover letter draft in your voice, emphasizing Python and leadership "
        "while staying true to your real experience., I'm a software engineer who ships "
        "reliable systems and leads teams to do the same every single day."
    )
    out = _strip_llm_preamble(pre)
    assert out.startswith("I'm a software engineer")
    assert "draft in your voice" not in out
    # Never eats a legitimate opening (no meta-preamble present).
    real = "Dear Hiring Manager, I have spent ten years building distributed systems at scale."
    assert _strip_llm_preamble(real) == real


class _RevisingLLM:
    """Returns a fixed revised body and records the start_tier of each call."""

    def __init__(self) -> None:
        self.start_tiers: list[int] = []
        self.revised = "Shipped a platform serving five million requests a day; cut deploy time."

    def is_configured(self) -> bool:
        return True

    def complete(self, messages, **kwargs):
        from applicant.ports.driven.llm import LLMResult

        self.start_tiers.append(kwargs.get("start_tier", 1))
        return LLMResult(text=self.revised, tier=2, model="fake")


@pytest.mark.unit
def test_revision_turn_uses_llm_at_tier_two_and_replaces_content(storage):
    """The redline 'request change' turn must actually revise via the LLM (not the
    old deterministic stub), escalated to L2 since editing material is heavy writing."""
    llm = _RevisingLLM()
    svc = MaterialService(
        storage, llm=llm, resume_tailoring=LatexTailor(), embedding=LocalEmbedding()
    )
    cid = CampaignId(new_id())
    doc = svc.generate_cover_letter(
        cid, ApplicationId(new_id()), "Shipped a data platform; reduced deploy time.", ["Python"],
    )
    llm.start_tiers.clear()
    session = svc.apply_turn(doc.id, "free_text", "Make it more concise.")
    # The turn ran the LLM at L2 and the document content is the revised text,
    # not the old "Applied free-text guidance: ..." stub echo.
    assert llm.start_tiers == [2]
    assert (session.redline_state or {}).get("content") == llm.revised
    stored = storage.documents.get(doc.id)
    assert stored.content == llm.revised
    assert all("Applied free-text guidance" not in t.ai_response for t in session.turns)


@pytest.mark.unit
def test_heavy_writing_escalates_to_tier_two(storage):
    """Résumé/cover-letter/essay writing is heavy, so it starts at L2 immediately
    instead of the cheap L1 default (an escalation before even trying L1)."""
    llm = _StartTierRecordingLLM()
    svc = MaterialService(
        storage, llm=llm, resume_tailoring=LatexTailor(), embedding=LocalEmbedding()
    )
    svc.generate_cover_letter(
        CampaignId(new_id()), ApplicationId(new_id()), "Python and SQL.", ["Python"],
    )
    assert llm.start_tiers and all(t == 2 for t in llm.start_tiers)


@pytest.mark.unit
def test_select_or_generate_rejects_llm_injected_fabrication(storage):
    """#17: a generated variant whose LLM body claims an unsupported skill raises
    TruthfulnessViolation (the fabrication gate now runs on generated variant bodies
    against the candidate's TRUE source, not source-to-self)."""
    svc = MaterialService(
        storage, llm=_FabricatingLLM(), resume_tailoring=LatexTailor(), embedding=LocalEmbedding()
    )
    cid = CampaignId(new_id())
    # No approved parent clears threshold -> fork + generate via the (fabricating) LLM.
    with pytest.raises(TruthfulnessViolation):
        svc.select_or_generate(
            cid, JobPostingId(new_id()), ["Kubernetes", "Rust"], BASE
        )


@pytest.mark.unit
def test_reframe_truthfully_reemphasizes_supported_terms_only(svc):
    """#17: reframe surfaces ONLY JD terms the source supports, never injecting an
    unsupported one (and it is no longer a verbatim no-op)."""
    src = "I built Python pipelines and wrote SQL."
    out = svc.reframe_truthfully(src, ["Python", "Go"])
    assert out != src  # real reframing, not a verbatim no-op
    assert out.startswith("Python.")  # supported term re-emphasized up front
    assert "Python" in out  # supported term surfaced
    # An unsupported JD term ("Go") is never injected into the reframed text.
    assert "Go" not in out
    # And the reframed output never trips the fabrication gate against the true source.
    svc.assert_no_fabrication(src, out)


@pytest.mark.unit
def test_fabrication_rejected_on_revision_turn(svc, storage):
    cid = CampaignId(new_id())
    aid = new_id()
    doc = svc.generate_cover_letter(cid, aid, "I built Python pipelines.", ["Python"])
    # A revision that injects a fabricated skill is rejected when truth is known.
    with pytest.raises(TruthfulnessViolation):
        svc.apply_turn(
            doc.id, "add", "Expert in Kubernetes orchestration",
            true_source="I built Python pipelines.",
        )


@pytest.mark.unit
def test_true_attribute_text_includes_attribute_cloud(svc, storage):
    from applicant.core.entities.attribute import Attribute
    from applicant.core.ids import AttributeId

    cid = CampaignId(new_id())
    storage.attributes.add(
        Attribute(id=AttributeId(new_id()), campaign_id=cid, name="skill:k8s", value="Kubernetes")
    )
    storage.commit()
    truth = svc.true_attribute_text(cid, BASE)
    # Now a Kubernetes claim is supported by the TRUE attribute set -> not fabricated.
    svc.assert_no_fabrication(truth, "Worked with Kubernetes.")  # no raise


# === non-AI-looking filters every pass (FR-RESUME-5) ======================
@pytest.mark.unit
def test_post_filter_strips_emdash_and_banned_and_scores_voice(svc):
    svc.set_banned_phrases(["rockstar ninja"])
    svc.load_voice_corpus(["I built pipelines and dashboards. I shipped fast."])
    report = svc.apply_post_filter("I am a rockstar ninja — I built pipelines.")
    assert "—" not in report.text
    assert "rockstar ninja" not in report.text.lower()
    assert report.em_dashes_stripped is True
    assert 0.0 <= report.voice_alignment <= 1.0


@pytest.mark.unit
def test_post_filter_is_idempotent(svc):
    svc.set_banned_phrases(["synergy"])
    once = svc.apply_post_filter("Synergy — driven results.").text
    twice = svc.apply_post_filter(once).text
    assert once == twice


# === cover letters on demand (FR-RESUME-10) ===============================
@pytest.mark.unit
def test_cover_letter_not_generated_when_role_does_not_warrant(svc):
    cid = CampaignId(new_id())
    doc = svc.generate_cover_letter(
        cid, new_id(), "I built Python pipelines.", ["Python"], campaign_default=False
    )
    assert doc is None


@pytest.mark.unit
def test_cover_letter_generated_when_role_requires(svc):
    cid = CampaignId(new_id())
    doc = svc.generate_cover_letter(
        cid, new_id(), "I built Python pipelines.", ["Python"], role_requires=True
    )
    assert doc is not None
    assert doc.type.value == "cover_letter"
    assert doc.approved is False


@pytest.mark.unit
def test_cover_letter_review_ready_notifies_and_materializes():
    from applicant.application.services.notification_service import NotificationService
    from applicant.application.services.pending_actions_service import PendingActionsService

    storage = InMemoryStorage()
    sent: list = []

    class _Spy:
        def notify(self, n):
            sent.append(n)
            return "h"

        def expire(self, k):  # pragma: no cover - not exercised here
            pass

    svc = MaterialService(
        storage,
        resume_tailoring=LatexTailor(),
        notifications=NotificationService(_Spy()),
        pending_actions=PendingActionsService(storage),
    )
    cid = CampaignId(new_id())
    doc = svc.generate_cover_letter(cid, new_id(), "Built Python pipelines.", ["Python"], role_requires=True)
    assert sent and str(doc.id) in (sent[-1].deep_link or "")
    pending = PendingActionsService(storage).list_pending(cid)
    assert any(p.kind == "material_review" for p in pending)


@pytest.mark.unit
def test_review_deep_link_targets_served_review_surface():
    """#5: the review deep link points at the SERVED /review surface, not the
    unserved /applicant/review.html default."""
    from applicant.application.services.notification_service import NotificationService
    from applicant.application.services.pending_actions_service import PendingActionsService

    storage = InMemoryStorage()
    sent: list = []

    class _Spy:
        def notify(self, n):
            sent.append(n)
            return "h"

        def expire(self, k):
            pass

    svc = MaterialService(
        storage,
        resume_tailoring=LatexTailor(),
        notifications=NotificationService(_Spy()),
        pending_actions=PendingActionsService(storage),
    )
    cid = CampaignId(new_id())
    doc = svc.generate_cover_letter(cid, new_id(), "Built Python pipelines.", ["Python"], role_requires=True)
    assert sent[-1].deep_link.startswith(f"/review?document_id={doc.id}")


@pytest.mark.unit
def test_approve_resolves_review_action_and_expires_ladder():
    """#5: approving a generated doc clears its material_review pending action AND
    expires the escalation ladder (the deep-link ref)."""
    from applicant.application.services.notification_service import NotificationService
    from applicant.application.services.pending_actions_service import PendingActionsService

    storage = InMemoryStorage()
    expired: list = []

    class _Spy:
        def notify(self, n):
            return "h"

        def expire(self, k):
            expired.append(k)

    pas = PendingActionsService(storage)
    svc = MaterialService(
        storage,
        resume_tailoring=LatexTailor(),
        notifications=NotificationService(_Spy()),
        pending_actions=pas,
    )
    cid = CampaignId(new_id())
    doc = svc.generate_cover_letter(cid, new_id(), "Built Python pipelines.", ["Python"], role_requires=True)
    # Before approval: the material_review pending action is open.
    assert any(p.kind == "material_review" for p in pas.list_pending(cid))

    svc.approve(doc.id)

    # After approval: the pending action is resolved and the ladder ref expired.
    assert not any(p.kind == "material_review" for p in pas.list_pending(cid))
    # NotificationService.acted("material_review:{id}") expires "decision:material_review:{id}".
    assert any(f"material_review:{doc.id}" in k for k in expired)


# === screening classification routing (FR-ANSWER-1) =======================
@pytest.mark.unit
def test_screening_essay_auto_classified_and_reviewed(svc):
    cid = CampaignId(new_id())
    doc = svc.generate_screening_answer(
        cid, new_id(), "Why do you want to work here?", "I love building pipelines.", essay=None
    )
    assert doc.type.value == "screening_answer"
    assert doc.approved is False


@pytest.mark.unit
def test_screening_factual_taken_from_true_source(svc):
    cid = CampaignId(new_id())
    doc = svc.generate_screening_answer(
        cid, new_id(), "How many years of Python?", "Eight years.", essay=None
    )
    assert doc.content == "Eight years."


@pytest.mark.unit
def test_screening_sensitive_declines_without_explicit_answer(svc):
    from applicant.core.rules.sensitive_fields import DECLINE_TO_SELF_IDENTIFY

    cid = CampaignId(new_id())
    doc = svc.generate_screening_answer(
        cid, new_id(), "What is your race/ethnicity?", "", essay=None
    )
    assert doc.content == DECLINE_TO_SELF_IDENTIFY


@pytest.mark.unit
def test_screening_sensitive_never_leaks_true_source(svc):
    # FR-ATTR-6/NFR-PRIV-1: a SENSITIVE answer must NEVER echo the flattened
    # true_source (attribute cloud / resume). Without an explicit EEO answer it
    # declines; the PII in true_source must not appear in the answer.
    from applicant.core.rules.sensitive_fields import DECLINE_TO_SELF_IDENTIFY

    cid = CampaignId(new_id())
    pii = "SSN 123-45-6789, 8 years at Acme, lives in Berlin."
    doc = svc.generate_screening_answer(
        cid, new_id(), "What is your race/ethnicity?", pii, essay=None
    )
    assert doc.content == DECLINE_TO_SELF_IDENTIFY
    assert "Acme" not in doc.content and "Berlin" not in doc.content


@pytest.mark.unit
def test_screening_sensitive_uses_explicit_answer_only(svc):
    # FR-ATTR-6: a SENSITIVE answer comes ONLY from the explicit stored EEO answer.
    cid = CampaignId(new_id())
    doc = svc.generate_screening_answer(
        cid,
        new_id(),
        "What is your gender?",
        "Lots of irrelevant PII here.",
        essay=None,
        explicit_answer="Prefer not to say",
    )
    assert doc.content == "Prefer not to say"
    assert "PII" not in doc.content


@pytest.mark.unit
def test_screening_gender_diversity_essay_is_not_declined(svc):
    # FR-ATTR-6/NFR-PRIV-1: a gender-DIVERSITY essay is an essay, not an EEO field;
    # it must not return the canned decline.
    from applicant.core.rules.sensitive_fields import DECLINE_TO_SELF_IDENTIFY

    cid = CampaignId(new_id())
    doc = svc.generate_screening_answer(
        cid,
        new_id(),
        "How do you foster gender diversity on a team?",
        "I have built inclusive teams and mentored junior engineers.",
        essay=None,
    )
    assert doc.content != DECLINE_TO_SELF_IDENTIFY


@pytest.mark.unit
def test_deferred_question_handoff_from_phase2(svc):
    # Phase 2 prefill defers essay screening questions to this entry point.
    cid = CampaignId(new_id())
    deferred = {"selector": "#q1", "label": "Describe a time you led a team.", "url": "/apply"}
    doc = svc.generate_for_deferred_question(cid, new_id(), deferred, "I led the data team.")
    assert doc.type.value == "screening_answer"
    assert doc.approved is False


# === durable + resumable revision sessions (FR-RESUME-8) ==================
@pytest.mark.unit
def test_revision_session_is_durable_and_resumable(storage):
    # A fresh service instance (simulating a restart) resumes the same session.
    svc1 = MaterialService(storage, resume_tailoring=LatexTailor())
    cid = CampaignId(new_id())
    doc = svc1.generate_cover_letter(cid, new_id(), "Built Python pipelines.", ["Python"], role_requires=True)
    svc1.apply_turn(doc.id, "add", "a true metric")
    svc2 = MaterialService(storage, resume_tailoring=LatexTailor())
    resumed = svc2.open_revision(doc.id)
    assert len(resumed.turns) == 1
    assert resumed.turns[0].kind == "add"


# === aggressiveness dial setter (FR-RESUME-9) =============================
@pytest.mark.unit
def test_aggressiveness_setter_clamps(svc):
    assert svc.set_aggressiveness(80) == 80
    assert svc.aggressiveness == 80
    assert svc.set_aggressiveness(500) == 100
    assert svc.set_aggressiveness(None) == 20


# === engine selection respects Phase 0 choice (FR-RESUME-3a) ==============
@pytest.mark.unit
def test_engine_selection_follows_conversion_choice(storage):
    from applicant.adapters.storage.app_config_store import InMemoryAppConfigStore

    conv = ConversionService(latex_tailor=LatexTailor(), config_store=InMemoryAppConfigStore())
    latex, docx = LatexTailor(), DocxTailor()
    svc = MaterialService(
        storage, resume_tailoring=latex, docx_tailoring=docx, conversion_service=conv
    )
    cid = CampaignId(new_id())
    # Default is docx until LaTeX is accepted (ConversionService default).
    assert svc.tailoring_for(cid) is docx
    conv.accept(str(cid))
    assert svc.tailoring_for(cid) is latex
    conv.reject(str(cid))
    assert svc.tailoring_for(cid) is docx
