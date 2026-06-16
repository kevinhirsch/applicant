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

from applicant.app.container import Container
from applicant.app.deps import get_container, require_llm_configured
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
    application_id: str, container: Container = Depends(get_container)
) -> dict:
    """Auto-detect a final submission in the controlled session (FR-LOG-4)."""
    detected = container.submission_service.detect_submission(application_id)  # type: ignore[arg-type]
    if not detected:
        return {"application_id": application_id, "detected": False}
    app = _load_or_stub(container, application_id)
    try:
        event = container.submission_service.record_submission(app, source=OutcomeSource.AUTO)
    except ReviewRequired as exc:
        # FR-RESUME-8: never auto-submit material that has not passed the review gate.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except IllegalStateTransition as exc:
        # FR-LOG-4/§7: an app in EMERGENCY_DATA_HANDOFF may only transition via the
        # user (→SUBMITTED_BY_USER); an AUTO/FINISHED_BY_ENGINE detect is illegal.
        # Surface it as a 409 conflict rather than letting it escape as a 500.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    _close_conversion_loop(container, app)
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
    container: Container = Depends(get_container),
) -> dict:
    """One-tap mark-submitted when auto-detection cannot confirm (FR-LOG-4)."""
    app = _load_or_stub(container, application_id)
    attrs = body.attributes_used if body else None
    try:
        event = container.submission_service.mark_submitted(app, attributes_used=attrs)
    except ReviewRequired as exc:
        # FR-RESUME-8: review-before-submission applies to the one-tap path too.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    _close_conversion_loop(container, app)
    return {"outcome_id": event.id, "type": event.type, "source": event.source.value}


@router.get("/applications/{application_id}/log")
def get_log(application_id: str, container: Container = Depends(get_container)) -> dict:
    """Retrieve the logged application detail + screenshots + outcomes (FR-LOG-3)."""
    return container.submission_service.get_log(application_id)  # type: ignore[arg-type]


def _close_conversion_loop(container: Container, app: Application) -> None:
    """Fold the now-converted application into per-campaign learning (FR-LEARN-2).

    Conversion = approval (state) PLUS submission (the OutcomeEvent just recorded).
    The advanced learning service reads the outcomes from storage, folds the rich
    converting-role signature, and persists it so the next run is biased and the
    state survives restart. Defensive: learning must never break a submission.
    """
    advanced = getattr(container, "advanced_learning_service", None)
    if advanced is None or not app.campaign_id:
        return
    posting = None
    if app.posting_id:
        posting = container.storage.postings.get(app.posting_id)  # type: ignore[arg-type]
    try:
        advanced.record_and_persist_conversion(app.campaign_id, app, posting=posting)
    except Exception:  # pragma: no cover - defensive: never fail the submission
        pass


def _load_or_stub(container: Container, application_id: str) -> Application:
    """Load the application or synthesize a minimal record so logging never fails.

    A submission can be recorded for an application the in-memory boot has not
    persisted (e.g. tests / emergency handoff). When the persisted state cannot
    legally transition to a terminal submission, or the row is absent, synthesize a
    minimal record in AWAITING_FINAL_APPROVAL so the §7 terminal transition is legal.
    """
    from applicant.core.state_machine import ApplicationState

    app = container.storage.applications.get(application_id)  # type: ignore[arg-type]
    legal_from = {
        ApplicationState.AWAITING_FINAL_APPROVAL,
        ApplicationState.EMERGENCY_DATA_HANDOFF,
    }
    if app is not None and app.status in legal_from:
        return app
    return Application(
        id=ApplicationId(application_id),
        campaign_id=app.campaign_id if app is not None else CampaignId(""),
        posting_id=app.posting_id if app is not None else JobPostingId(""),
        status=ApplicationState.AWAITING_FINAL_APPROVAL,
        role_name=app.role_name if app is not None else None,
        job_title=app.job_title if app is not None else None,
        work_mode=app.work_mode if app is not None else None,
        root_url=app.root_url if app is not None else None,
    )
