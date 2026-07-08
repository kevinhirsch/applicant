"""Outcomes router (FR-LOG-1/2/3/4, FR-LEARN-2).

Phase 1 wired one-tap mark-submitted (the manual outcome path); Phase 2 adds
auto-detection (confirmation-page heuristics), full per-application logging with
per-page screenshots, and a minimal retrieval surface (FR-LOG-3). Every submission
records an OutcomeEvent so conversion learning sees real conversions (FR-LEARN-2).
Gated behind the LLM-settings gate (FR-UI-5).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from applicant.app.deps import (
    get_storage,
    get_submission_service,
    require_llm_configured,
)
from applicant.core.entities.application import Application
from applicant.core.entities.outcome_event import OutcomeSource
from applicant.core.errors import IllegalStateTransition, ReviewRequired
from applicant.core.ids import (
    ApplicationId,
    CampaignId,
    JobPostingId,
)

router = APIRouter(
    prefix="/api/outcomes", tags=["outcomes"], dependencies=[Depends(require_llm_configured)]
)


class MarkSubmittedIn(BaseModel):
    attributes_used: dict | None = None


@router.get("")
def index() -> dict:
    return {"surface": "outcomes", "phase": 2, "status": "live"}


@router.post("/applications/{application_id}/detect", status_code=200)
def detect_submission(
    application_id: str,
    submission=Depends(get_submission_service),
    storage=Depends(get_storage),
) -> dict:
    """Auto-detect a final submission in the controlled session (FR-LOG-4)."""
    detected = submission.detect_submission(application_id)  # type: ignore[arg-type]
    if not detected:
        return {"application_id": application_id, "detected": False}
    app = _load_or_stub(storage, application_id)
    try:
        event = submission.record_submission(app, source=OutcomeSource.AUTO)
    except ReviewRequired as exc:
        # FR-RESUME-8: never auto-submit material that has not passed the review gate.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except IllegalStateTransition as exc:
        # FR-LOG-4/§7: an app in EMERGENCY_DATA_HANDOFF may only transition via the
        # user (→SUBMITTED_BY_USER); an AUTO/FINISHED_BY_ENGINE detect is illegal.
        # Surface it as a 409 conflict rather than letting it escape as a 500.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    # Conversion learning is now folded inside SubmissionService.record_submission so
    # EVERY submit path closes the loop exactly once (#2) — do not double-fold here.
    return {
        "application_id": application_id,
        "detected": True,
        "outcome_id": event.id,
        "source": event.source.value,
    }


@router.post("/applications/{application_id}/mark-submitted", status_code=201)
def mark_submitted(
    application_id: str,
    body: MarkSubmittedIn | None = None,
    submission=Depends(get_submission_service),
    storage=Depends(get_storage),
) -> dict:
    """One-tap mark-submitted when auto-detection cannot confirm (FR-LOG-4)."""
    app = _load_or_stub(storage, application_id)
    attrs = body.attributes_used if body else None
    try:
        event = submission.mark_submitted(app, attributes_used=attrs)
    except ReviewRequired as exc:
        # FR-RESUME-8: review-before-submission applies to the one-tap path too.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    # Conversion learning is folded inside SubmissionService.record_submission (#2).
    return {"outcome_id": event.id, "type": event.type, "source": event.source.value}


@router.get("/applications/{application_id}/log")
def get_log(application_id: str, submission=Depends(get_submission_service)) -> dict:
    """Retrieve the logged application detail + screenshots + outcomes (FR-LOG-3)."""
    return submission.get_log(application_id)  # type: ignore[arg-type]


@router.get("/applications/{application_id}/snapshot")
def get_snapshot(application_id: str, storage=Depends(get_storage)) -> dict:
    """Retrieve the immutable submission snapshot for an application (#372).

    Returns the exact answers, material versions, posting, and timestamp that
    were recorded at the stop-boundary — the durable evidence of what was
    submitted. 404 when no snapshot has been recorded for the application.

    H3 (full-fidelity review): ``stage`` says WHERE the snapshot was captured —
    ``"reviewed"`` (the pre-submit stop-boundary: this is exactly what will be
    sent) or ``"submitted"`` (the terminal record: exactly what was sent). The
    reviewed payload is promoted to submitted byte-identical, so the two stages
    always carry the same content for one application.
    """
    snap = storage.submission_snapshots.get_for_application(
        ApplicationId(application_id)
    )
    if snap is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No submission snapshot recorded for this application.",
        )
    return {
        "application_id": str(snap.application_id),
        "answers": dict(snap.answers or {}),
        "material_versions": dict(getattr(snap, "material_versions", {}) or {}),
        "materials": list(snap.materials or []),
        "posting_url": getattr(snap, "posting_url", "") or "",
        "timestamp": snap.captured_at.isoformat() if snap.captured_at else None,
        "stage": snap.stage,
    }


def _load_or_stub(storage, application_id: str) -> Application:
    """Load the application for a terminal submission, enforcing the §7 gate.

    A PERSISTED application may only record an outcome from a legal ``from`` state
    for the terminal transition (AWAITING_FINAL_APPROVAL or EMERGENCY_DATA_HANDOFF).
    If the persisted row is in a non-legal pre-state (PREFILLING / BLOCKED_* / ...),
    raise ``IllegalStateTransition`` (->409) rather than fabricating a passing
    AWAITING_FINAL_APPROVAL record that lets an outcome be recorded for an app that
    never legally reached the gate (#3).

    When NO row exists (tests / in-memory boot that never persisted), synthesize a
    minimal AWAITING_FINAL_APPROVAL record so logging still works — that is a
    genuinely-absent record, not an override of a real persisted status.
    """
    from applicant.core.state_machine import ApplicationState

    app = storage.applications.get(application_id)  # type: ignore[arg-type]
    legal_from = {
        ApplicationState.AWAITING_FINAL_APPROVAL,
        ApplicationState.EMERGENCY_DATA_HANDOFF,
    }
    if app is not None:
        if app.status in legal_from:
            return app
        # Persisted but in an illegal pre-state for the gate — do NOT synthesize.
        raise IllegalStateTransition(app.status, ApplicationState.SUBMITTED_BY_USER)
    return Application(
        id=ApplicationId(application_id),
        campaign_id=CampaignId(""),
        posting_id=JobPostingId(""),
        status=ApplicationState.AWAITING_FINAL_APPROVAL,
    )
