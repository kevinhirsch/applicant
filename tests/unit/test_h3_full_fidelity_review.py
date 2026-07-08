"""H3 — full-fidelity review: what the owner reviews is EXACTLY what is submitted.

The honesty invariant (road-to-market Phase 1.5, H3): before every submit the owner
sees the **literal** payload — every filled value verbatim, the exact documents, the
posting — never a summary. These tests pin the whole engine chain:

* pre-fill landing at the ``AWAITING_FINAL_APPROVAL`` stop-boundary records a
  provisional ``stage="reviewed"`` submission snapshot with the literal filled
  values (verbatim, keyed by the human label when the engine knows one);
* the snapshot is readable BEFORE any submit via the outcomes snapshot route (the
  pre-submit 404 gap is closed);
* requesting final approval refreshes the reviewed snapshot with the live
  document/variant set while preserving the captured answers;
* the terminal submit promotes the reviewed payload BYTE-IDENTICAL — only the stage
  marker flips to ``submitted`` — so the reviewed record IS the submitted record;
* the review-before-submit boundary (ties to P2-8) still holds: unapproved material
  raises ``ReviewRequired`` and the reviewed snapshot is left untouched;
* a submitted snapshot is immutable — a later boundary pass can never rewrite it.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from applicant.adapters.orchestration.checkpoint_shim import CheckpointShimOrchestrator
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.agent_loop import AgentLoop
from applicant.application.services.agent_run_service import AgentRunService
from applicant.application.services.final_approval_service import FinalApprovalService
from applicant.application.services.submission_service import SubmissionService
from applicant.core.entities.campaign import Campaign, RunMode
from applicant.core.entities.decision import Decision, DecisionType
from applicant.core.entities.generated_document import DocumentType, GeneratedDocument
from applicant.core.entities.job_posting import JobPosting
from applicant.core.entities.outcome_event import OutcomeSource
from applicant.core.entities.submission_snapshot import (
    STAGE_REVIEWED,
    STAGE_SUBMITTED,
)
from applicant.core.errors import ReviewRequired
from applicant.core.ids import (
    CampaignId,
    DecisionId,
    GeneratedDocumentId,
    JobPostingId,
    new_id,
)
from applicant.core.state_machine import ApplicationState

NOW = datetime(2026, 7, 6, tzinfo=UTC)


# --- fakes (mirroring tests/unit/test_agent_loop.py) -------------------------


class _FakeScoring:
    def score_posting(self, posting, criteria=None):
        from applicant.core.entities.viability_scoring import ViabilityScoring

        return ViabilityScoring(posting_id=posting.id, score=0.9, rationale="fit")

    def is_viable(self, scoring):
        return True


class _FakeDigest:
    def deliver(self, campaign_id, criteria=None):
        return {"payload": {"rows": [{"posting_id": "p"}]}}


class _LiteralPrefillResult:
    """A pre-fill outcome carrying the LITERAL filled payload (verbatim)."""

    def __init__(self, state):
        self.state = state
        self.filled_by_page = {
            "https://ats.example.com/apply": {
                "#first-name": "Ada",
                "#salary": "185000",
                "#q-why": "Because I shipped exactly this stack for 6 years.",
            }
        }
        self.generated_answers = [
            {
                "selector": "#q-why",
                "label": "Why do you want this role?",
                "answer": "Because I shipped exactly this stack for 6 years.",
                "url": "https://ats.example.com/apply",
            }
        ]
        self.uploaded_documents = [
            {
                "selector": "#resume-upload",
                "label": "Resume/CV",
                "path": "/data/resumes/ada-resume.pdf",
                "url": "https://ats.example.com/apply",
            }
        ]


class _LiteralPrefill:
    def prefill_application(self, application, url, attributes=None, *, cautious=True):
        return _LiteralPrefillResult(ApplicationState.AWAITING_FINAL_APPROVAL)


def _make_campaign(storage):
    cid = CampaignId(new_id())
    storage.campaigns.add(
        Campaign(id=cid, name="C", run_mode=RunMode.CONTINUOUS, throughput_target=15, schedule={})
    )
    return cid


def _approve_posting(storage, cid):
    pid = JobPostingId(new_id())
    storage.postings.add(
        JobPosting(id=pid, campaign_id=cid, title="Engineer", company="Acme", source_url="http://x")
    )
    storage.decisions.add(
        Decision(id=DecisionId(new_id()), application_id=str(pid), type=DecisionType.APPROVE)
    )
    return pid


def _loop(storage, orch, **kw):
    return AgentLoop(
        storage=storage,
        agent_run_service=AgentRunService(storage),
        scoring_service=_FakeScoring(),
        digest_service=_FakeDigest(),
        orchestrator=orch,
        **kw,
    )


def _park_at_gate(storage, orch):
    """Drive one application through pre-fill to the final-approval gate."""
    cid = _make_campaign(storage)
    _approve_posting(storage, cid)
    submission = SubmissionService(storage)
    fa = FinalApprovalService(orch)
    loop = _loop(
        storage,
        orch,
        prefill_service=_LiteralPrefill(),
        submission_service=submission,
        final_approval_service=fa,
    )
    loop.run_once(cid, now=NOW)
    app = storage.applications.list_for_campaign(cid)[0]
    return loop, app, fa, cid


# --- the reviewed snapshot exists BEFORE any submit --------------------------


@pytest.mark.unit
def test_stop_boundary_records_the_literal_payload_before_any_submit(tmp_path):
    storage = InMemoryStorage()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    _loop_, app, _fa, _cid = _park_at_gate(storage, orch)

    # Nothing was submitted — the pipeline is parked at the recv gate.
    assert storage.outcomes.list_for_application(app.id) == []

    snap = storage.submission_snapshots.get_for_application(app.id)
    assert snap is not None, "the stop-boundary must record the reviewed payload"
    assert snap.stage == STAGE_REVIEWED

    # Every filled value, verbatim — keyed by the human label when known.
    assert snap.answers["#first-name"] == "Ada"
    assert snap.answers["#salary"] == "185000"
    assert (
        snap.answers["Why do you want this role?"]
        == "Because I shipped exactly this stack for 6 years."
    )
    # The labelled screening answer replaces its raw-selector key, not duplicates it.
    assert "#q-why" not in snap.answers

    # The exact uploaded résumé file is named, and the posting is the real URL.
    uploads = [m for m in snap.materials if m.get("kind") == "uploaded_file"]
    assert uploads and uploads[0]["name"] == "ada-resume.pdf"
    assert snap.posting_url == "http://x"


@pytest.mark.unit
def test_snapshot_route_serves_the_reviewed_payload_pre_submit(tmp_path):
    """The outcomes snapshot route no longer 404s pre-submit — the review surface
    ("Review exactly what will be sent") gets the literal payload with its stage."""
    from applicant.app.routers.outcomes import get_snapshot

    storage = InMemoryStorage()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    _loop_, app, _fa, _cid = _park_at_gate(storage, orch)

    body = get_snapshot(str(app.id), storage=storage)
    assert body["stage"] == STAGE_REVIEWED
    assert body["answers"]["#first-name"] == "Ada"
    assert body["posting_url"] == "http://x"
    assert body["timestamp"] is not None


# --- refresh at request-approval keeps answers, adds materials ---------------


@pytest.mark.unit
def test_request_approval_refresh_adds_documents_and_keeps_answers(tmp_path):
    storage = InMemoryStorage()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    loop, app, _fa, _cid = _park_at_gate(storage, orch)

    # A cover letter is generated AFTER pre-fill (the material step runs later).
    doc = GeneratedDocument(
        id=GeneratedDocumentId(new_id()),
        campaign_id=app.campaign_id,
        application_id=app.id,
        type=DocumentType.COVER_LETTER,
        content="Dear Acme…",
        approved=True,
    )
    storage.documents.add(doc)

    # The refresh pass at the request-approval boundary (res=None).
    loop._record_presubmit_snapshot(app, None)

    snap = storage.submission_snapshots.get_for_application(app.id)
    assert snap.stage == STAGE_REVIEWED
    # Captured answers survive the refresh untouched.
    assert snap.answers["#first-name"] == "Ada"
    # The exact document is now part of the reviewed payload.
    kinds = {m.get("kind") for m in snap.materials}
    assert "cover_letter" in kinds
    assert snap.material_versions["cover_letter"] == str(doc.id)
    # The pre-fill-time upload record is carried forward, not dropped.
    assert "uploaded_file" in kinds


def test_failed_refresh_keeps_the_previous_reviewed_snapshot(tmp_path):
    """A failure while REBUILDING the reviewed snapshot must leave the owner with
    the previous reviewed payload — never with nothing (Greptile on #746: the old
    snapshot is deleted only after the replacement is fully built)."""
    storage = InMemoryStorage()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    loop, app, _fa, _cid = _park_at_gate(storage, orch)

    before = storage.submission_snapshots.get_for_application(app.id)
    assert before is not None and before.stage == STAGE_REVIEWED

    # Make the build blow up mid-way (documents read happens after the old
    # delete used to run) — the recorder swallows and logs, but the previous
    # reviewed snapshot must survive.
    class _Boom:
        def list_for_application(self, _id):
            raise RuntimeError("boom")

    real_docs = storage.documents
    storage.documents = _Boom()
    try:
        loop._record_presubmit_snapshot(app, None)
    finally:
        storage.documents = real_docs

    after = storage.submission_snapshots.get_for_application(app.id)
    assert after is not None, "a failed rebuild must not delete the prior reviewed payload"
    assert after.id == before.id
    assert after.answers == before.answers


# --- reviewed == submitted (byte-identical promotion) -------------------------


@pytest.mark.unit
def test_submit_promotes_the_reviewed_snapshot_byte_identical(tmp_path):
    storage = InMemoryStorage()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    loop, app, fa, cid = _park_at_gate(storage, orch)

    reviewed = storage.submission_snapshots.get_for_application(app.id)
    assert reviewed.stage == STAGE_REVIEWED

    # The owner authorizes; the parked pipeline completes through the REAL service.
    fa.submit_decision(f"application:{app.id}", str(app.id), "finished_by_engine")
    loop.run_once(cid, now=NOW)

    assert storage.applications.get(app.id).status is ApplicationState.FINISHED_BY_ENGINE
    submitted = storage.submission_snapshots.get_for_application(app.id)
    # Same record, same content — only the stage marker flips.
    assert submitted.id == reviewed.id
    assert submitted.answers == reviewed.answers
    assert submitted.materials == reviewed.materials
    assert submitted.material_versions == reviewed.material_versions
    assert submitted.posting_url == reviewed.posting_url
    assert submitted.captured_at == reviewed.captured_at
    assert submitted.stage == STAGE_SUBMITTED


# --- the review-before-submit boundary still holds (ties to P2-8) ------------


@pytest.mark.unit
def test_unapproved_material_blocks_submit_and_leaves_reviewed_snapshot(tmp_path):
    storage = InMemoryStorage()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    loop, app, fa, cid = _park_at_gate(storage, orch)

    # Unapproved generated material appears for the app — the gate must hold.
    storage.documents.add(
        GeneratedDocument(
            id=GeneratedDocumentId(new_id()),
            campaign_id=app.campaign_id,
            application_id=app.id,
            type=DocumentType.COVER_LETTER,
            content="Dear Acme…",
            approved=False,
        )
    )
    gated = storage.applications.get(app.id)
    with pytest.raises(ReviewRequired):
        SubmissionService(storage).record_submission(gated, source=OutcomeSource.AUTO)
    # Nothing was recorded and the reviewed payload is untouched.
    assert storage.outcomes.list_for_application(app.id) == []
    snap = storage.submission_snapshots.get_for_application(app.id)
    assert snap.stage == STAGE_REVIEWED


# --- submitted evidence is immutable ------------------------------------------


@pytest.mark.unit
def test_submitted_snapshot_is_never_rewritten_by_a_later_boundary_pass(tmp_path):
    storage = InMemoryStorage()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    loop, app, fa, cid = _park_at_gate(storage, orch)

    fa.submit_decision(f"application:{app.id}", str(app.id), "finished_by_engine")
    loop.run_once(cid, now=NOW)
    submitted = storage.submission_snapshots.get_for_application(app.id)
    assert submitted.stage == STAGE_SUBMITTED

    # A stray later boundary pass must not touch the submitted evidence.
    loop._record_presubmit_snapshot(
        storage.applications.get(app.id),
        _LiteralPrefillResult(ApplicationState.AWAITING_FINAL_APPROVAL),
    )
    unchanged = storage.submission_snapshots.get_for_application(app.id)
    assert unchanged.id == submitted.id
    assert unchanged.stage == STAGE_SUBMITTED
    assert unchanged.answers == submitted.answers


# --- legacy snapshots read as submitted ---------------------------------------


@pytest.mark.unit
def test_legacy_snapshot_without_stage_reads_as_submitted():
    from applicant.core.entities.submission_snapshot import SubmissionSnapshot
    from applicant.core.ids import ApplicationId, SubmissionSnapshotId

    legacy = SubmissionSnapshot(
        id=SubmissionSnapshotId(new_id()),
        application_id=ApplicationId(new_id()),
        answers={"q": "a"},
    )
    assert legacy.stage == STAGE_SUBMITTED
