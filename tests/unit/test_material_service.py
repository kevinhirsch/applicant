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
from applicant.core.errors import ReviewRequired, TruthfulnessViolation
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


@pytest.fixture
def strict_svc(storage) -> MaterialService:
    """MaterialService under STRICT truth policy — the fabrication guard HARD-BLOCKS.
    Verifies the strict enforcement path still holds after P1-13 made BALANCED the
    default (BALANCED surfaces invented facts for review instead of blocking)."""
    return MaterialService(
        storage,
        llm=None,
        resume_tailoring=LatexTailor(),
        embedding=LocalEmbedding(),
        truth_policy="strict",
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


# === truthfulness on generation + revision (FR-RESUME-2, P1-13) ===========
@pytest.mark.unit
def test_fabrication_surfaced_by_default_blocked_in_strict(svc):
    """P1-13 truth policy. BALANCED (default): an invented fact is SURFACED (returned
    for review), never silently blocked or kept — a human approves every send. STRICT
    retains the historical hard-fail."""
    from applicant.core.rules.truthfulness import TruthPolicy

    flagged = svc.assert_no_fabrication("Python and SQL.", "Expert in Kubernetes.")
    assert any("kubernet" in f.lower() for f in flagged), "invented fact must be surfaced"
    with pytest.raises(TruthfulnessViolation):
        svc.assert_no_fabrication(
            "Python and SQL.", "Expert in Kubernetes.", policy=TruthPolicy.STRICT
        )


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


class _GenThenFabricateLLM:
    """Clean text on the first (generation) call; injects an entity-shaped
    fabrication on the second (revision) call."""

    def __init__(self):
        self.calls = 0

    def is_configured(self) -> bool:
        return True

    def complete(self, messages, **kwargs):
        from applicant.ports.driven.llm import LLMResult

        self.calls += 1
        text = (
            "Shipped a data platform and reduced deploy time."
            if self.calls == 1
            else "I led the platform team at Microsoft starting in 2015."
        )
        return LLMResult(text=text, tier=2, model="fake")


@pytest.mark.unit
def test_revision_runs_fabrication_guard_without_caller_true_source(storage):
    """A redline turn carries NO true_source from the front-door, so the guard was
    silently skipped — a revision could inject a fabricated claim. The guard now
    derives the ground truth from the campaign + approved content and rejects a NEW
    entity-shaped fabrication ("Microsoft"/"2015") even with no caller true_source."""
    llm = _GenThenFabricateLLM()
    svc = MaterialService(
        storage, llm=llm, resume_tailoring=LatexTailor(), embedding=LocalEmbedding(),
        truth_policy="strict",
    )
    cid = CampaignId(new_id())
    doc = svc.generate_cover_letter(
        cid, ApplicationId(new_id()), "Shipped a data platform; reduced deploy time.", ["Python"],
    )
    # No true_source passed (mirrors the front-door turn) — the derived guard must still
    # RUN (not be bypassed). Under STRICT it hard-fails on the new fabrication; under
    # BALANCED the same detection surfaces it for review instead of blocking.
    with pytest.raises(TruthfulnessViolation):
        svc.apply_turn(doc.id, "free_text", "Add my leadership experience.")


@pytest.mark.unit
def test_revision_allows_benign_rephrase_without_true_source(storage):
    """The derived guard must NOT false-flag a benign rephrase of approved content
    (no new entity-shaped claims) — low false-positive is required."""
    llm = _RevisingLLM()
    svc = MaterialService(
        storage, llm=llm, resume_tailoring=LatexTailor(), embedding=LocalEmbedding()
    )
    cid = CampaignId(new_id())
    doc = svc.generate_cover_letter(
        cid, ApplicationId(new_id()), "Shipped a data platform; reduced deploy time.", ["Python"],
    )
    session = svc.apply_turn(doc.id, "free_text", "Make it more concise.")  # must NOT raise
    assert (session.redline_state or {}).get("content") == llm.revised


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
        storage, llm=_FabricatingLLM(), resume_tailoring=LatexTailor(),
        embedding=LocalEmbedding(), truth_policy="strict",
    )
    cid = CampaignId(new_id())
    # No approved parent clears threshold -> fork + generate via the (fabricating) LLM.
    # STRICT: the injected unsupported skill hard-fails. (BALANCED surfaces it instead.)
    with pytest.raises(TruthfulnessViolation):
        svc.select_or_generate(
            cid, JobPostingId(new_id()), ["Kubernetes", "Rust"], BASE
        )


class _ExhaustingLLM:
    """An LLM that is configured but whose ladder is fully exhausted (e.g. every
    configured tier returns a hard auth error)."""

    def is_configured(self) -> bool:
        return True

    def complete(self, messages, **kwargs):
        from applicant.ports.driven.llm import LLMLadderExhausted

        raise LLMLadderExhausted("all tiers failed")


@pytest.mark.unit
def test_generate_text_marks_degraded_on_ladder_exhaustion(storage):
    """Regression: a configured-but-exhausted LLM (e.g. misconfigured 401 upper tier)
    must NOT masquerade as a real generation. The deterministic reframe is used as a
    last resort AND the pass is marked degraded so a canned draft is visible."""
    svc = MaterialService(
        storage, llm=_ExhaustingLLM(), resume_tailoring=LatexTailor(), embedding=LocalEmbedding()
    )
    src = "I built Python pipelines and wrote SQL."
    out = svc._generate_text(src, ["Python"], kind="essay_answer")
    # Falls back to the deterministic reframe (last resort), not empty/crashing.
    assert out == svc.reframe_truthfully(src, ["Python"])
    # …and the fallback is OBSERVABLE, not silent.
    assert svc.last_generation_degraded is True
    assert svc.silent_failure_count >= 1


@pytest.mark.unit
def test_generate_text_not_degraded_on_real_generation(storage):
    """A successful generation does NOT set the degraded marker."""
    svc = MaterialService(
        storage,
        llm=_StartTierRecordingLLM(),
        resume_tailoring=LatexTailor(),
        embedding=LocalEmbedding(),
    )
    svc._generate_text("I write Python and SQL.", ["Python"], kind="essay_answer")
    assert svc.last_generation_degraded is False


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
def test_fabrication_rejected_on_revision_turn_strict(strict_svc, storage):
    cid = CampaignId(new_id())
    aid = new_id()
    doc = strict_svc.generate_cover_letter(cid, aid, "I built Python pipelines.", ["Python"])
    # STRICT: a revision that injects a fabricated skill is hard-rejected when truth is
    # known. (BALANCED would instead surface it for review — a human approves every send.)
    with pytest.raises(TruthfulnessViolation):
        strict_svc.apply_turn(
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


# === P1-13 flagged-facts surfacing (balanced truth policy) ================
def _store_doc(storage, cid, content, *, dtype=None, application_id=None):
    from applicant.core.entities.generated_document import DocumentType, GeneratedDocument
    from applicant.core.ids import GeneratedDocumentId

    doc = GeneratedDocument(
        id=GeneratedDocumentId(new_id()),
        campaign_id=cid,
        application_id=application_id or ApplicationId(new_id()),
        type=dtype or DocumentType.COVER_LETTER,
        content=content,
        approved=False,
    )
    storage.documents.add(doc)
    storage.commit()
    return doc


@pytest.mark.unit
def test_flagged_facts_surfaces_unsupported_and_omits_supported(svc, storage):
    """The read-only surfacing recomputes the fact-class tokens a stored draft
    uses that aren't in the profile — invented specifics are flagged while the
    ones traceable to the attribute cloud are not (P1-13; BALANCED surfaces, never
    blocks)."""
    from applicant.core.entities.attribute import Attribute
    from applicant.core.ids import AttributeId

    cid = CampaignId(new_id())
    storage.attributes.add(
        Attribute(id=AttributeId(new_id()), campaign_id=cid, name="skill:py", value="Python")
    )
    storage.commit()
    doc = _store_doc(
        storage, cid, "I built Python pipelines and deployed on Kubernetes at Stanford."
    )
    out = svc.flagged_facts_for_document(doc.id)
    assert out["document_id"] == str(doc.id)
    assert out["campaign_id"] == str(cid)
    assert out["type"] == "cover_letter"
    assert "Kubernetes" in out["flagged"]
    assert "Stanford" in out["flagged"]
    # Python is in the true attribute cloud -> supported -> never flagged.
    assert "Python" not in out["flagged"]


@pytest.mark.unit
def test_flagged_facts_clean_draft_returns_empty(svc, storage):
    """A draft whose specifics all trace to the profile flags nothing (the panel
    then renders nothing) — the honest 'clean' signal, not a fabricated one."""
    from applicant.core.entities.attribute import Attribute
    from applicant.core.ids import AttributeId

    cid = CampaignId(new_id())
    storage.attributes.add(
        Attribute(id=AttributeId(new_id()), campaign_id=cid, name="skill:py", value="Python")
    )
    storage.commit()
    doc = _store_doc(storage, cid, "I am glad to bring my Python experience to your team.")
    out = svc.flagged_facts_for_document(doc.id)
    assert out["flagged"] == []


@pytest.mark.unit
def test_flagged_facts_missing_document_raises_not_found(svc):
    from applicant.core.errors import NotFound
    from applicant.core.ids import GeneratedDocumentId

    with pytest.raises(NotFound):
        svc.flagged_facts_for_document(GeneratedDocumentId(new_id()))


# === visible provenance (H4) ==============================================
def _seed_h4_profile(storage, cid):
    from applicant.core.entities.attribute import Attribute
    from applicant.core.ids import AttributeId

    for name, value in (("Skills", "Python"), ("Employer", "Acme Corp")):
        storage.attributes.add(
            Attribute(id=AttributeId(new_id()), campaign_id=cid, name=name, value=value)
        )
    storage.commit()


@pytest.mark.unit
def test_line_provenance_traces_each_line_to_named_sources(svc, storage):
    """H4: the review surface can trace each generated line to the owner's real
    history — every fact-class token names WHICH profile attribute supports it,
    and unsourced tokens come back flagged (empty sources), never hidden."""
    cid = CampaignId(new_id())
    _seed_h4_profile(storage, cid)
    doc = _store_doc(
        storage, cid, "I built Python systems at Acme.\nI ran Kubernetes at Stanford."
    )
    out = svc.line_provenance_for_document(doc.id)
    assert out["document_id"] == str(doc.id)
    assert out["campaign_id"] == str(cid)
    assert out["type"] == "cover_letter"
    assert out["checked"] is True
    assert len(out["lines"]) == 2
    first = {f["token"]: f["sources"] for f in out["lines"][0]["facts"]}
    assert first["Python"] == ["your profile (Skills)"]
    assert first["Acme"] == ["your profile (Employer)"]
    second = {f["token"]: f["sources"] for f in out["lines"][1]["facts"]}
    assert second["Kubernetes"] == []  # unsourced -> flagged, not hidden
    assert second["Stanford"] == []
    assert set(out["unsourced"]) == {"Kubernetes", "Stanford"}


@pytest.mark.unit
def test_line_provenance_agrees_with_flagged_facts(svc, storage):
    """The provenance view's unsourced set is exactly the fabrication guard's
    flagged set (same tokenizers/matchers), so the two review panels can never
    disagree about what is or isn't traceable."""
    cid = CampaignId(new_id())
    _seed_h4_profile(storage, cid)
    doc = _store_doc(
        storage, cid, "I deployed Python on Kubernetes at Stanford in 2015."
    )
    prov = svc.line_provenance_for_document(doc.id)
    flagged = svc.flagged_facts_for_document(doc.id)
    assert set(prov["unsourced"]) == set(flagged["flagged"])


@pytest.mark.unit
def test_line_provenance_empty_document_says_unchecked_not_clean(svc, storage):
    """H-series: a document with no reviewable text must return checked=False
    with a reason — the absence of a check must never render as a clean check."""
    cid = CampaignId(new_id())
    doc = _store_doc(storage, cid, "")
    out = svc.line_provenance_for_document(doc.id)
    assert out["checked"] is False
    assert out["reason"]
    assert out["lines"] == []
    assert out["unsourced"] == []


@pytest.mark.unit
def test_line_provenance_missing_document_raises_not_found(svc):
    from applicant.core.errors import NotFound
    from applicant.core.ids import GeneratedDocumentId

    with pytest.raises(NotFound):
        svc.line_provenance_for_document(GeneratedDocumentId(new_id()))


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
def test_generation_extracts_voice_from_the_users_resume(storage, svc):
    """FR-RESUME-5: generation must be constrained to the candidate's OWN voice — the
    corpus is extracted from their uploaded résumé in the live flow (previously the
    corpus was never loaded, so the voice directive fell back to generic)."""
    from applicant.core.entities.onboarding_profile import OnboardingProfile
    from applicant.core.ids import OnboardingProfileId

    cid = CampaignId(new_id())
    storage.onboarding_profiles.add(
        OnboardingProfile(
            id=OnboardingProfileId(new_id()),
            campaign_id=cid,
            completion_flag=True,
            intake={
                "base_resume": {
                    "raw_text": (
                        "Architected resilient distributed pipelines. "
                        "Spearheaded analytics dashboards for stakeholders."
                    ),
                    "document_path": "x",
                }
            },
        )
    )
    storage.commit()
    assert svc.voice.is_empty  # nothing loaded until generation runs
    svc.generate_cover_letter(cid, new_id(), "", ["Python"], role_requires=True)
    # The voice profile is now the user's own résumé corpus (not the generic default).
    assert not svc.voice.is_empty
    assert {"pipelines", "dashboards", "analytics"} & svc.voice.vocabulary


@pytest.mark.unit
def test_approve_is_refused_until_the_review_is_opened():
    """FR-NOTIF-4: "approve only after viewing" — approving a document before its
    redline review was opened is refused (server-side, non-bypassable); approval
    succeeds once the review session exists."""
    svc = MaterialService(InMemoryStorage(), resume_tailoring=LatexTailor())
    cid = CampaignId(new_id())
    doc = svc.generate_cover_letter(
        cid, new_id(), "Built Python pipelines.", ["Python"], role_requires=True
    )
    # Straight from notification → approve, with no view: refused.
    with pytest.raises(ReviewRequired):
        svc.approve(doc.id)
    assert svc._storage.documents.get(doc.id).approved is False
    # Opening the redline review (what the front-door "Review" button does) unblocks it.
    svc.open_revision(doc.id)
    approved = svc.approve(doc.id)
    assert approved.approved is True


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

    svc.open_revision(doc.id)  # FR-NOTIF-4: approve only after viewing the review.
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


class _FailingConfigStore:
    """A config store double whose ``set`` always raises — simulates a storage
    hiccup (disk full, DB blip) during persistence."""

    def set(self, key, value):
        raise RuntimeError("store unavailable")


@pytest.mark.unit
def test_aggressiveness_persist_failure_degrades_but_logs(storage, monkeypatch):
    """Audit #46: ``_persist_aggressiveness`` used to swallow a store failure with a
    bare ``except Exception: pass`` and zero trace — the user's chosen value would
    silently fail to survive a restart with no way for an operator to notice. The
    in-request behavior must stay unchanged (the chosen value still wins for the rest
    of this instance's lifetime, and the setter still returns it cleanly, no
    exception escapes to the caller) — only a warning is now logged so the failure is
    at least observable.

    Intercepts the ``warning()`` call on the exact logger the service uses rather than
    relying on ``caplog`` — a prior test elsewhere in a full-suite run may reconfigure
    logging (its own handlers, ``propagate=False``, a global ``logging.disable(...)``),
    which drops the record before any handler runs and makes ``caplog``-based capture
    order-dependent/flaky (the same pattern documented in
    ``test_db_fallback_healthcheck.py::test_build_storage_marks_unreachable_db_as_fallback``).
    """
    import applicant.application.services.material_service as material_service_module

    recorded: list[str] = []
    monkeypatch.setattr(
        material_service_module.log,
        "warning",
        lambda msg, *a, **k: recorded.append(msg % a if a else msg),
    )

    svc = MaterialService(storage, resume_tailoring=LatexTailor(), config_store=_FailingConfigStore())
    result = svc.set_aggressiveness(65)
    # Success-path behavior is unchanged: the setter still returns the clamped value
    # and the instance still reflects it, despite the store failure.
    assert result == 65
    assert svc.aggressiveness == 65
    # But now there is a trace of the failure instead of total silence.
    assert any("aggressiveness" in msg.lower() for msg in recorded)


@pytest.mark.unit
def test_aggressiveness_persist_success_is_unaffected_by_the_logging_change(storage, monkeypatch):
    """Control: a normal (non-failing) persist path logs nothing and behaves exactly
    as before — the logging addition only fires on the failure branch."""
    import applicant.application.services.material_service as material_service_module
    from applicant.adapters.storage.app_config_store import InMemoryAppConfigStore

    recorded: list[str] = []
    monkeypatch.setattr(
        material_service_module.log,
        "warning",
        lambda msg, *a, **k: recorded.append(msg % a if a else msg),
    )

    svc = MaterialService(
        storage, resume_tailoring=LatexTailor(), config_store=InMemoryAppConfigStore()
    )
    result = svc.set_aggressiveness(65)
    assert result == 65
    assert svc.aggressiveness == 65
    assert not recorded


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


# === degraded-draft flag reaches persisted material (dark-engine audit #40) ===
# Regression for the "review UI presents a fallback draft as a real generation"
# gap: MaterialService.last_generation_degraded / silent_failure_count already
# existed but reached no persisted material and no router — a degraded cover
# letter / screening essay / résumé variant looked identical to a real one once
# read back from storage. These assert the sentinel actually survives the
# storage round trip (not just the in-process property checked above).


@pytest.mark.unit
def test_cover_letter_marks_degraded_marker_in_provenance_on_ladder_exhaustion(storage):
    svc = MaterialService(
        storage, llm=_ExhaustingLLM(), resume_tailoring=LatexTailor(), embedding=LocalEmbedding()
    )
    cid = CampaignId(new_id())
    doc = svc.generate_cover_letter(
        cid, new_id(), "I built Python pipelines.", ["Python"], role_requires=True
    )
    assert doc is not None
    assert any(p.kind == MaterialService.DEGRADED_PROVENANCE_KIND for p in doc.provenance)
    # The degraded sentinel is excluded from `_provenance_payload` at the router
    # layer (tested there); here just confirm it round-trips through storage.
    reloaded = storage.documents.get(doc.id)
    assert any(
        p.kind == MaterialService.DEGRADED_PROVENANCE_KIND for p in reloaded.provenance
    )


@pytest.mark.unit
def test_cover_letter_not_marked_degraded_on_real_generation(storage):
    svc = MaterialService(
        storage,
        llm=_StartTierRecordingLLM(),
        resume_tailoring=LatexTailor(),
        embedding=LocalEmbedding(),
    )
    cid = CampaignId(new_id())
    doc = svc.generate_cover_letter(
        cid, new_id(), "Python and SQL.", ["Python"], role_requires=True
    )
    assert doc is not None
    assert not any(p.kind == MaterialService.DEGRADED_PROVENANCE_KIND for p in doc.provenance)


@pytest.mark.unit
def test_screening_essay_marks_degraded_marker_on_ladder_exhaustion(storage):
    svc = MaterialService(
        storage, llm=_ExhaustingLLM(), resume_tailoring=LatexTailor(), embedding=LocalEmbedding()
    )
    cid = CampaignId(new_id())
    doc = svc.generate_screening_answer(
        cid, new_id(), "Why do you want to work here?", "I love building pipelines.", essay=True
    )
    assert any(p.kind == MaterialService.DEGRADED_PROVENANCE_KIND for p in doc.provenance)


@pytest.mark.unit
def test_screening_factual_answer_never_marked_degraded_even_with_exhausted_llm(storage):
    """Factual answers never call the LLM, so an exhausted ladder is irrelevant —
    regression guard against the marker leaking onto a path that never generates."""
    svc = MaterialService(
        storage, llm=_ExhaustingLLM(), resume_tailoring=LatexTailor(), embedding=LocalEmbedding()
    )
    cid = CampaignId(new_id())
    doc = svc.generate_screening_answer(
        cid, new_id(), "How many years of Python?", "Eight years.", essay=False
    )
    assert not any(p.kind == MaterialService.DEGRADED_PROVENANCE_KIND for p in doc.provenance)


@pytest.mark.unit
def test_resume_variant_fork_marks_degraded_in_fit_scores_on_ladder_exhaustion(storage):
    svc = MaterialService(
        storage, llm=_ExhaustingLLM(), resume_tailoring=LatexTailor(), embedding=LocalEmbedding()
    )
    cid = CampaignId(new_id())
    result = svc.select_or_generate(cid, JobPostingId(new_id()), ["Kubernetes"], BASE)
    assert result.generated is True
    assert result.variant.fit_scores.get(MaterialService.DEGRADED_FIT_SCORE_KEY) is True
    reloaded = storage.resume_variants.get(result.variant.id)
    assert reloaded.fit_scores.get(MaterialService.DEGRADED_FIT_SCORE_KEY) is True


@pytest.mark.unit
def test_resume_variant_fork_not_marked_degraded_on_real_generation(storage):
    svc = MaterialService(
        storage,
        llm=_StartTierRecordingLLM(),
        resume_tailoring=LatexTailor(),
        embedding=LocalEmbedding(),
    )
    cid = CampaignId(new_id())
    result = svc.select_or_generate(cid, JobPostingId(new_id()), ["Kubernetes"], BASE)
    assert result.generated is True
    assert MaterialService.DEGRADED_FIT_SCORE_KEY not in result.variant.fit_scores
