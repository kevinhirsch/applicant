"""P2-8 — the "human final say" invariant, made citable.

THE CLAIM: **no code path records a final submission without an approval
record, and no approval exists without the review actually having been
opened.** Two layers pin it, like the truthfulness claim
(``test_truth_claim_evidence.py``):

* BEHAVIORAL — every submit-recording entry (auto-detect, one-tap
  mark-submitted, the durable pipeline's call) funnels through
  ``SubmissionService.record_submission``, which enforces the review gate
  BEFORE anything is recorded: unapproved generated material ⇒
  ``ReviewRequired`` and nothing is stored. Approval itself refuses until the
  redline review surface has been opened (``MaterialService.approve``).
* STRUCTURAL — the only production writer of a ``type="submitted"``
  ``OutcomeEvent`` is that gated service. A new construction site outside the
  audited allowlist turns this suite red, so a bypass cannot appear silently.

Reproduce:
    DATABASE_URL='postgresql+psycopg://x:x@127.0.0.1:1/none' \
      uv run pytest -q tests/unit/test_final_say_invariant.py
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from applicant.adapters.resume_tailoring.latex_tailor import LatexTailor
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.material_service import MaterialService
from applicant.application.services.submission_service import SubmissionService
from applicant.core.entities.application import Application, ApplicationState
from applicant.core.entities.generated_document import DocumentType, GeneratedDocument
from applicant.core.entities.outcome_event import OutcomeSource
from applicant.core.errors import ReviewRequired
from applicant.core.ids import (
    ApplicationId,
    CampaignId,
    GeneratedDocumentId,
    JobPostingId,
    new_id,
)

SRC_ROOT = pathlib.Path(__file__).resolve().parents[2] / "src" / "applicant"


@pytest.fixture
def storage() -> InMemoryStorage:
    return InMemoryStorage()


def _app(status=ApplicationState.AWAITING_FINAL_APPROVAL) -> Application:
    return Application(
        id=ApplicationId(new_id()),
        campaign_id=CampaignId(new_id()),
        posting_id=JobPostingId(new_id()),
        status=status,
        role_name="Senior Engineer",
        job_title="Senior Engineer",
        work_mode="remote",
        root_url="https://acme.example-ats.com/job/123",
    )


def _unapproved_doc(storage, app) -> GeneratedDocument:
    doc = GeneratedDocument(
        id=GeneratedDocumentId(new_id()),
        campaign_id=app.campaign_id,
        application_id=app.id,
        type=DocumentType.COVER_LETTER,
        content="I built Python data pipelines.",
        approved=False,
    )
    storage.documents.add(doc)
    storage.commit()
    return doc


# ── behavioral: the gate refuses, and nothing is recorded ───────────────────


@pytest.mark.unit
@pytest.mark.parametrize("source", [OutcomeSource.AUTO, OutcomeSource.MANUAL])
def test_submission_with_unapproved_material_is_refused_and_records_nothing(
    storage, source
):
    """Both submit sources (auto-detected and user-marked) hit the same wall:
    unapproved generated material ⇒ ReviewRequired, zero outcomes stored."""
    app = _app()
    _unapproved_doc(storage, app)
    svc = SubmissionService(storage)

    with pytest.raises(ReviewRequired):
        svc.record_submission(app, source=source)

    assert storage.outcomes.list_for_application(app.id) == []


@pytest.mark.unit
def test_one_tap_mark_submitted_funnels_through_the_same_gate(storage):
    app = _app()
    _unapproved_doc(storage, app)
    storage.applications.add(app)
    storage.commit()
    svc = SubmissionService(storage)

    with pytest.raises(ReviewRequired):
        svc.mark_submitted(app)

    assert storage.outcomes.list_for_application(app.id) == []


@pytest.mark.unit
def test_an_unapproved_linked_resume_variant_also_blocks(storage):
    """The résumé side of the gate: a generated variant linked to the
    application gates submission until approved."""
    from applicant.core.entities.resume_variant import ResumeVariant
    from applicant.core.ids import ResumeVariantId

    app = _app()
    variant = ResumeVariant(
        id=ResumeVariantId(new_id()),
        campaign_id=app.campaign_id,
        storage_path="variants/x.tex",
        approved=False,
    )
    storage.resume_variants.add(variant)
    app = Application(
        **{
            **app.__dict__,
            "resume_variant_id": variant.id,
        }
    )
    storage.applications.add(app)
    storage.commit()

    with pytest.raises(ReviewRequired):
        SubmissionService(storage).record_submission(app, source=OutcomeSource.MANUAL)


@pytest.mark.unit
def test_approval_itself_requires_the_review_to_have_been_opened(storage):
    """The approval record cannot exist without the review surface having
    been opened — the second link in the chain."""
    material = MaterialService(storage, llm=None, resume_tailoring=LatexTailor())
    app = _app()
    doc = _unapproved_doc(storage, app)

    with pytest.raises(ReviewRequired):
        material.approve(doc.id)

    material.open_revision(doc.id)
    approved = material.approve(doc.id)
    assert approved.approved is True


@pytest.mark.unit
def test_the_full_chain_review_then_approve_then_submit(storage):
    """The whole invariant end-to-end: review opened → approval recorded →
    submission recorded. Remove any link and the earlier tests refuse."""
    material = MaterialService(storage, llm=None, resume_tailoring=LatexTailor())
    app = _app()
    storage.applications.add(app)
    storage.commit()
    doc = _unapproved_doc(storage, app)

    material.open_revision(doc.id)
    material.approve(doc.id)
    event = SubmissionService(storage).record_submission(
        app, source=OutcomeSource.MANUAL
    )

    assert event.type == "submitted"
    recorded = storage.outcomes.list_for_application(app.id)
    assert [e.type for e in recorded] == ["submitted"]


# ── structural: the gated service is the ONLY submitted-outcome writer ──────

#: Files allowed to construct OutcomeEvent, with the reason each is safe.
_OUTCOME_CONSTRUCTOR_ALLOWLIST = {
    # The gated funnel itself: record_submission enforces ensure_submittable
    # before this constructor can run (the behavioral tests above).
    "application/services/submission_service.py",
    # Post-submission outcomes only (rejected / ghosted / interview / offer …):
    # its maps cannot emit "submitted" — pinned by the test below.
    "application/services/post_submission_service.py",
    # Demo-mode fixtures: synthetic showcase data, not a submit path.
    "application/services/dev_seed.py",
    # Row → entity rehydration of already-recorded events.
    "adapters/storage/repositories.py",
}


def _outcome_event_calls() -> list[tuple[str, ast.Call]]:
    """Every REAL ``OutcomeEvent(...)`` constructor call in the engine source.

    AST-based on purpose: a docstring or comment that merely mentions
    ``OutcomeEvent(submitted)`` must neither trip nor satisfy this invariant —
    only actual constructor calls count."""
    calls: list[tuple[str, ast.Call]] = []
    for path in SRC_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        rel = path.relative_to(SRC_ROOT).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")
                if name == "OutcomeEvent":
                    calls.append((rel, node))
    return calls


def _constructor_files() -> set[str]:
    return {rel for rel, _ in _outcome_event_calls()}


@pytest.mark.unit
def test_no_outcome_event_constructor_exists_outside_the_audited_allowlist():
    """A NEW OutcomeEvent construction site anywhere in the engine turns this
    red — a submission writer cannot appear without being audited here."""
    unexpected = _constructor_files() - _OUTCOME_CONSTRUCTOR_ALLOWLIST
    assert not unexpected, (
        "new OutcomeEvent constructor(s) outside the audited allowlist: "
        f"{sorted(unexpected)} — if intentional, prove the path is gated and "
        "add it here with its reason"
    )


@pytest.mark.unit
def test_submitted_outcomes_are_constructed_only_by_the_gated_service_and_demo_seed():
    """Only the gated service (and the demo seeder's synthetic fixtures) may
    construct a submitted-type outcome. Judged on the ACTUAL constructor
    keyword, not text matching."""
    offenders: set[str] = set()
    for rel, call in _outcome_event_calls():
        for kw in call.keywords:
            if (
                kw.arg == "type"
                and isinstance(kw.value, ast.Constant)
                and kw.value.value == "submitted"
            ):
                offenders.add(rel)
    assert offenders == {
        "application/services/submission_service.py",
        "application/services/dev_seed.py",
    }, f"unexpected submitted-outcome writer set: {sorted(offenders)}"


@pytest.mark.unit
def test_post_submission_outcome_maps_cannot_emit_submitted():
    """The post-submission service records rejections / interviews / offers /
    ghosting — never a submission. Its outcome vocabularies are pinned."""
    from applicant.application.services import post_submission_service as pss

    assert "submitted" not in pss._MANUAL_OUTCOME_STATUS
    keywords = [
        kw.lower()
        for kw in (
            list(getattr(pss.PostSubmissionService, "INTERVIEW_KEYWORDS", []))
            + list(getattr(pss.PostSubmissionService, "OFFER_KEYWORDS", []))
        )
    ]
    assert keywords, "keyword vocabularies must exist (the maps moved? re-pin them)"
