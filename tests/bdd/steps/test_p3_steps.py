"""Step bindings for the Phase 3 acceptance scenarios (master spec §10).

Maps the §10 anchors to the real Phase 3 service + adapters + core rules so the
scenarios pass with NO TeX/LibreOffice/LLM installed:

* "Resume uploads right and looks right" -> select/generate + fidelity check.
* "Interactive resume review with highlighted edits" -> redline + revision loop +
  review gate.
* "Screening answers go through review" -> FR-ANSWER-1 + review gate.
* "Adaptation never fabricates" -> truthfulness guardrail + em-dash post-filter.

Every scenario maps to >=1 requirement ID (cited in the feature files):
FR-RESUME-2/3/4/5/6/7/8, FR-ANSWER-1, FR-FONT-2, NFR-TRUTH-1.
Phase-local fixtures live here, not in the shared conftest.
"""

from __future__ import annotations

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from applicant.adapters.resume_tailoring.docx_tailor import DocxTailor
from applicant.adapters.resume_tailoring.latex_tailor import LatexTailor
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.material_service import MaterialService
from applicant.core.entities.resume_variant import ResumeVariant
from applicant.core.errors import ReviewRequired, TruthfulnessViolation
from applicant.core.ids import CampaignId, JobPostingId, ResumeVariantId, new_id
from applicant.core.rules.truthfulness import contains_emdash

scenarios(
    "../features/p3_material_generation.feature",
    "../features/p3_interactive_review.feature",
    "../features/p3_screening_answers.feature",
    "../features/p3_truthfulness.feature",
    "../features/p3_cover_letter_on_demand.feature",
)


# --- phase-local fixtures --------------------------------------------------
@pytest.fixture
def p3ctx() -> dict:
    return {}


@pytest.fixture
def p3_storage() -> InMemoryStorage:
    return InMemoryStorage()


@pytest.fixture
def material(p3_storage) -> MaterialService:
    # No LLM wired -> deterministic truthful fallback (never fabricates, never blocks).
    # render_mode="off" forces the stub: BASE_SOURCE is a minimal, non-compilable
    # fragment for the fidelity contract, so this scenario stays green on a host that
    # HAS a TeX engine (e.g. the deploy image). Real compiles: integration render tests.
    return MaterialService(p3_storage, llm=None, resume_tailoring=LatexTailor(render_mode="off"))


BASE_SOURCE = (
    "\\section{Skills}\n"
    "Python developer who built data pipelines.\n"
    "Wrote SQL for analytics dashboards.\n"
)


# === Material generation ===================================================
@given("a campaign with an approved base resume variant")
def approved_base_variant(p3ctx, p3_storage):
    cid = CampaignId(new_id())
    p3ctx["campaign_id"] = cid
    base = ResumeVariant(
        id=ResumeVariantId(new_id()),
        campaign_id=cid,
        storage_path="variants/base.tex",
        approved=True,
    )
    p3_storage.resume_variants.add(base)
    p3_storage.commit()
    p3ctx["base"] = base


@given("a posting whose required terms are only partly covered by the base resume")
def partly_covered_posting(p3ctx):
    p3ctx["posting_id"] = JobPostingId(new_id())
    # Python is covered by the base source; Kubernetes/Terraform are not.
    p3ctx["jd_terms"] = ["Python", "Kubernetes", "Terraform"]


@when("the engine selects or generates a resume variant for the posting")
def select_or_generate(p3ctx, material):
    p3ctx["selection"] = material.select_or_generate(
        p3ctx["campaign_id"], p3ctx["posting_id"], p3ctx["jd_terms"], BASE_SOURCE
    )


@then("a new variant is forked from the base with parent lineage")
def variant_forked(p3ctx):
    sel = p3ctx["selection"]
    assert sel.generated is True
    assert sel.variant.parent_id == p3ctx["base"].id  # lineage (FR-RESUME-6)


@then("the new variant is not yet approved")
def variant_unapproved(p3ctx):
    assert p3ctx["selection"].variant.approved is False


@then("the rendered artifact passes the compile-and-visually-inspect fidelity check")
def artifact_fidelity_ok(p3ctx, material):
    result = material._resume_tailoring.render_artifact(
        p3ctx["selection"].variant.id, BASE_SOURCE
    )
    p3ctx["render"] = result
    assert result.fidelity_ok is True


@then("the rendered fonts are embedded and no em-dash remains")
def fonts_embedded_no_emdash(p3ctx):
    result = p3ctx["render"]
    assert "fonts not embedded" not in result.notes
    assert "em-dash survived" not in result.notes


# --- docx fallback engine fidelity (FR-RESUME-3/4) -------------------------
@given("a campaign whose chosen material engine is docx")
def docx_engine_campaign(p3ctx):
    # render_mode="off" forces the deterministic stub (mirroring the `material`
    # fixture above): the scenario asserts the SOURCE-level fidelity contract, and
    # in "auto" with no converter installed the adapter now honestly reports the
    # missing toolchain instead of claiming a faithful render.
    p3ctx["docx_engine"] = DocxTailor(render_mode="off")


@when("the docx engine renders the base resume artifact")
def docx_render(p3ctx):
    p3ctx["render"] = p3ctx["docx_engine"].render_artifact(
        ResumeVariantId(new_id()), "Senior engineer — built data pipelines"
    )


@then("the docx artifact passes the compile-and-visually-inspect fidelity check")
def docx_fidelity_ok(p3ctx):
    assert p3ctx["render"].fidelity_ok is True


@then("the docx fonts are embedded and no em-dash remains")
def docx_fonts_embedded_no_emdash(p3ctx):
    result = p3ctx["render"]
    assert "fonts not embedded" not in result.notes
    assert "em-dash survived" not in result.notes


# === Interactive review ====================================================
@given("a generated resume document awaiting review")
def generated_resume_doc(p3ctx, material):
    cid = CampaignId(new_id())
    aid = new_id()
    p3ctx["campaign_id"] = cid
    p3ctx["application_id"] = aid
    doc = material.generate_cover_letter(cid, aid, BASE_SOURCE, ["Python"])
    # Reuse the cover-letter generator path to mint a stored, unapproved doc.
    p3ctx["doc"] = doc


@given("the application carries that unapproved generated document")
def application_carries_doc(p3ctx):
    assert p3ctx["doc"].approved is False


@when("the user opens the redline review")
def open_redline(p3ctx, material):
    p3ctx["session"] = material.open_revision(p3ctx["doc"].id)
    p3ctx["redline"] = material.render_redline(
        ResumeVariantId(new_id()), "alpha beta", "alpha gamma"
    )


@when("the user submits an add revision turn")
def add_turn(p3ctx, material):
    p3ctx["session"] = material.apply_turn(p3ctx["doc"].id, "add", "a true metric")


@when("the user submits a subtract revision turn")
def subtract_turn(p3ctx, material):
    p3ctx["session"] = material.apply_turn(p3ctx["doc"].id, "subtract", "filler")


@then("the redline shows additions and deletions highlighted")
def redline_highlighted(p3ctx):
    rl = p3ctx["redline"]
    assert "redline-add" in rl.rendered_html
    assert "redline-sub" in rl.rendered_html


@then("submission is blocked while the document is unapproved")
def submission_blocked(p3ctx, material):
    with pytest.raises(ReviewRequired):
        material.ensure_application_submittable(p3ctx["application_id"])


@when("the user approves the document")
def approve_doc(p3ctx, material):
    p3ctx["approved"] = material.approve(p3ctx["doc"].id)


@then("the document is approved")
def doc_approved(p3ctx):
    assert p3ctx["approved"].approved is True


@then("submission is no longer blocked by the review gate")
def submission_unblocked(p3ctx, material):
    material.ensure_application_submittable(p3ctx["application_id"])  # must not raise


# === Screening answers =====================================================
@given("a screening question and the candidate's true source material")
def essay_question(p3ctx):
    p3ctx["campaign_id"] = CampaignId(new_id())
    p3ctx["application_id"] = new_id()
    p3ctx["question"] = "Why do you want this role?"
    p3ctx["true_source"] = "I built Python data pipelines and enjoy mentoring."


@when("the engine generates an essay screening answer")
def gen_essay(p3ctx, material):
    p3ctx["doc"] = material.generate_screening_answer(
        p3ctx["campaign_id"],
        p3ctx["application_id"],
        p3ctx["question"],
        p3ctx["true_source"],
        essay=True,
    )


@then("the answer is stored unapproved")
def answer_unapproved(p3ctx, material):
    stored = material._storage.documents.get(p3ctx["doc"].id)
    assert stored is not None and stored.approved is False


@then("submission is blocked while the screening answer is unapproved")
def screening_blocked(p3ctx, material):
    with pytest.raises(ReviewRequired):
        material.ensure_application_submittable(p3ctx["application_id"])


@when("the user approves the screening answer")
def approve_screening(p3ctx, material):
    material.approve(p3ctx["doc"].id)


@given("a factual screening question and the candidate's true source material")
def factual_question(p3ctx):
    p3ctx["campaign_id"] = CampaignId(new_id())
    p3ctx["application_id"] = new_id()
    p3ctx["question"] = "How many years of Python experience?"
    # Note the em-dash in the true source: the post-filter must strip it.
    p3ctx["true_source"] = "Eight years — primarily Python."


@when("the engine generates a factual screening answer")
def gen_factual(p3ctx, material):
    p3ctx["doc"] = material.generate_screening_answer(
        p3ctx["campaign_id"],
        p3ctx["application_id"],
        p3ctx["question"],
        p3ctx["true_source"],
        essay=False,
    )


@then("the answer contains no em-dash")
def factual_no_emdash(p3ctx):
    assert not contains_emdash(p3ctx["doc"].content or "")


# === Truthfulness ==========================================================
@given(parsers.parse("the candidate's true source mentions Python and SQL but not Kubernetes"))
def true_source_no_k8s(p3ctx):
    p3ctx["true_source"] = "Built Python services and wrote SQL for analytics."


@given("a job description emphasizing Python and Kubernetes")
def jd_python_k8s(p3ctx):
    p3ctx["jd_terms"] = ["Python", "Kubernetes"]


@when("the engine reframes the source toward the job description")
def reframe(p3ctx, material):
    p3ctx["reframed"] = material.reframe_truthfully(p3ctx["true_source"], p3ctx["jd_terms"])


@then("the reframed text still surfaces the real Python experience")
def reframed_has_python(p3ctx):
    assert "Python" in p3ctx["reframed"]


@then("the reframed text does not claim Kubernetes")
def reframed_no_k8s(p3ctx):
    assert "Kubernetes" not in p3ctx["reframed"]


@then("attempting to inject a Kubernetes claim is rejected as a truthfulness violation")
def inject_k8s_rejected(p3ctx, material):
    # STRICT pins the hard-reject. Under the P1-13 BALANCED default the injected claim
    # is surfaced for review instead of blocked (a human approves every send); the
    # reframe path itself never *adds* a missing skill in either mode.
    from applicant.core.rules.truthfulness import TruthPolicy

    fabricated = p3ctx["true_source"] + "\nExpert in Kubernetes orchestration."
    with pytest.raises(TruthfulnessViolation):
        material.assert_no_fabrication(
            p3ctx["true_source"], fabricated, policy=TruthPolicy.STRICT
        )


@given("generated material containing an em-dash")
def material_with_emdash(p3ctx):
    p3ctx["text"] = "Senior engineer — shipped features — fast."


@when("the non-AI-looking post-filter runs")
def run_post_filter(p3ctx, material):
    p3ctx["report"] = material.apply_post_filter(p3ctx["text"])


@then("no em-dash remains in the output")
def no_emdash_remains(p3ctx):
    assert not contains_emdash(p3ctx["report"].text)


@then("the output is stable when filtered again")
def stable_idempotent(p3ctx, material):
    again = material.apply_post_filter(p3ctx["report"].text)
    assert again.text == p3ctx["report"].text


# === interactive review: filters re-run on every turn (FR-RESUME-5/8) ======
@when("the user submits a free-text turn instructing it to be more concise")
def free_text_turn(p3ctx, material):
    p3ctx["session"] = material.apply_turn(p3ctx["doc"].id, "free_text", "make it more concise")


@when("the user submits an add turn that introduces an em-dash")
def add_emdash_turn(p3ctx, material):
    # The instruction carries an em-dash; the post-filter MUST strip it on the turn.
    p3ctx["session"] = material.apply_turn(p3ctx["doc"].id, "add", "Led teams — shipped fast")


@then("the revised content carries no em-dash")
def revised_no_emdash(p3ctx, material):
    stored = material._storage.documents.get(p3ctx["doc"].id)
    assert stored is not None
    assert not contains_emdash(stored.content or "")
    assert not contains_emdash(p3ctx["session"].redline_state.get("content", ""))


@then("the session records the add and free-text turns")
def session_records_turns(p3ctx):
    kinds = [t.kind for t in p3ctx["session"].turns]
    assert "free_text" in kinds
    assert "add" in kinds


# === cover letter on demand (FR-RESUME-10) =================================
class _RecordingNotifier:
    """Minimal NotificationPort spy: records emitted notifications (FR-NOTIF-4)."""

    def __init__(self) -> None:
        self.sent: list = []

    def notify(self, notification) -> str:
        self.sent.append(notification)
        return f"handle-{len(self.sent)}"

    def expire(self, dedup_key: str) -> None:
        pass


@pytest.fixture
def review_notifier() -> _RecordingNotifier:
    return _RecordingNotifier()


@pytest.fixture
def material_with_notify(p3_storage, review_notifier) -> MaterialService:
    from applicant.application.services.notification_service import NotificationService
    from applicant.application.services.pending_actions_service import PendingActionsService

    return MaterialService(
        p3_storage,
        llm=None,
        resume_tailoring=LatexTailor(render_mode="off"),  # stub: see `material` fixture
        notifications=NotificationService(review_notifier),
        pending_actions=PendingActionsService(p3_storage),
    )


@given("a campaign whose cover-letter default is off")
def cover_default_off(p3ctx):
    p3ctx["campaign_id"] = CampaignId(new_id())
    p3ctx["application_id"] = new_id()
    p3ctx["campaign_default"] = False


@given("the candidate's true source for the cover letter")
def cover_true_source(p3ctx):
    # Carries an em-dash so the deterministic post-filter must strip it.
    p3ctx["true_source"] = "I built Python data pipelines — and mentored engineers."


@when("the engine considers a cover letter for a role with no override")
def consider_cover_no_override(p3ctx, material_with_notify):
    p3ctx["doc"] = material_with_notify.generate_cover_letter(
        p3ctx["campaign_id"],
        p3ctx["application_id"],
        "I built Python pipelines.",
        ["Python"],
        campaign_default=p3ctx["campaign_default"],
        role_requires=None,
    )


@then("no cover letter is generated")
def no_cover_generated(p3ctx):
    assert p3ctx["doc"] is None


@when("the engine generates a cover letter for a role that requires one")
def generate_cover_required(p3ctx, material_with_notify):
    p3ctx["doc"] = material_with_notify.generate_cover_letter(
        p3ctx["campaign_id"],
        p3ctx["application_id"],
        p3ctx["true_source"],
        ["Python"],
        campaign_default=p3ctx["campaign_default"],
        role_requires=True,
    )
    p3ctx["material"] = material_with_notify


@then("the cover letter is stored unapproved")
def cover_stored_unapproved(p3ctx):
    assert p3ctx["doc"] is not None
    assert p3ctx["doc"].approved is False


@then("the cover letter contains no em-dash")
def cover_no_emdash(p3ctx):
    assert not contains_emdash(p3ctx["doc"].content or "")


@then("a review-ready notification linked to the review surface is emitted")
def cover_notification_emitted(p3ctx, review_notifier):
    assert review_notifier.sent, "expected a review-ready notification (FR-NOTIF-4)"
    note = review_notifier.sent[-1]
    assert note.deep_link and str(p3ctx["doc"].id) in note.deep_link
    # And a pending action was materialized in the home base.
    pending = p3ctx["material"]._pending_actions.list_pending(p3ctx["campaign_id"])
    assert any(pa.kind == "material_review" for pa in pending)


@then("submission is blocked while the cover letter is unapproved")
def cover_submission_blocked(p3ctx):
    with pytest.raises(ReviewRequired):
        p3ctx["material"].ensure_application_submittable(p3ctx["application_id"])


@when("the user approves the cover letter")
def approve_cover(p3ctx):
    p3ctx["material"].approve(p3ctx["doc"].id)
