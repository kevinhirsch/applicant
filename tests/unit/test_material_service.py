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
from applicant.core.ids import CampaignId, JobPostingId, ResumeVariantId, new_id

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
