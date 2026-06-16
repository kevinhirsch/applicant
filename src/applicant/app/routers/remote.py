"""Remote router (FR-SANDBOX-2/3, FR-PREFILL-5).

# STAGE B — owned by Phase 2.

Remote-session control surface: get the one-click live-session (VNC) URL, and at
the final-submit step let the user either **submit themselves** in the live session
or **authorize the engine to finish** (friction-free). Authorizing the engine
routes the final click through the core pre-fill-stop boundary so the engine can
only ever click final submit *with* explicit authorization (FR-PREFILL-5); without
it the boundary raises and the route returns 403.

Both terminal paths record an OutcomeEvent(submitted) so learning sees conversions
(FR-LOG-4, FR-LEARN-2). Gated behind the LLM-settings gate (FR-UI-5).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from applicant.app.container import Container
from applicant.app.deps import get_container, require_automated_work, require_llm_configured
from applicant.core.entities.outcome_event import OutcomeSource
from applicant.core.errors import PrefillBoundaryViolation, ReviewRequired
from applicant.core.rules.prefill_boundary import StepKind, ensure_action_allowed

router = APIRouter(
    prefix="/api/remote",
    tags=["remote"],
    dependencies=[Depends(require_llm_configured), Depends(require_automated_work)],
)


class OpenSessionIn(BaseModel):
    application_id: str


@router.get("")
def index() -> dict:
    return {"surface": "remote", "phase": 2, "status": "live"}


@router.post("/sessions", status_code=201)
def open_session(body: OpenSessionIn, container: Container = Depends(get_container)) -> dict:
    """Provision a sandbox and return its one-click live-session URL (FR-SANDBOX-2)."""
    session = container.sandbox.provision(body.application_id)  # type: ignore[arg-type]
    return {
        "session_id": session.session_id,
        "application_id": session.application_id,
        "view_url": session.remote_view_url,
    }


@router.get("/sessions/{session_id}/view-url")
def view_url(session_id: str, container: Container = Depends(get_container)) -> dict:
    """Return the live-session URL for an existing session (FR-SANDBOX-2)."""
    return {
        "session_id": session_id,
        "view_url": container.sandbox.remote_view().view_url(session_id),
    }


@router.post("/sessions/{session_id}/takeover", status_code=204)
def authorize_takeover(session_id: str, container: Container = Depends(get_container)) -> None:
    """Hand live control of the session to the user (FR-SANDBOX-3)."""
    container.sandbox.remote_view().authorize_takeover(session_id)


@router.post("/applications/{application_id}/request-final-approval", status_code=202)
def request_final_approval(
    application_id: str, container: Container = Depends(get_container)
) -> dict:
    """Notify the user the application awaits final approval (FR-NOTIF-2/4).

    Fires the escalation ladder with a one-click live-session link + a redline-surface
    seam (FR-NOTIF-4); the durable ``recv`` gate is awaited by the workflow worker.
    """
    session = container.sandbox.for_application(application_id)  # type: ignore[arg-type]
    url = session.remote_view_url if session else None
    handle = container.final_approval_service.request_approval(application_id, session_url=url)
    return {"application_id": application_id, "notification": handle, "gate": "awaiting"}


@router.post("/applications/{application_id}/submit-self", status_code=201)
def submit_self(application_id: str, container: Container = Depends(get_container)) -> dict:
    """User submitted themselves in the live session (FR-PREFILL-5, FR-LOG-4)."""
    try:
        event = _record_submission(container, application_id, source=OutcomeSource.MANUAL)
    except ReviewRequired as exc:
        # FR-RESUME-8: even self-submit cannot record over unapproved material.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    # Acting on one channel expires the other escalation rungs (FR-NOTIF-3).
    container.final_approval_service.acted(application_id)
    return {
        "application_id": application_id,
        "result": "submitted_by_user",
        "outcome_id": event.id,
    }


@router.post("/applications/{application_id}/authorize-engine-finish", status_code=201)
def authorize_engine_finish(
    application_id: str, container: Container = Depends(get_container)
) -> dict:
    """Authorize the engine to click the final submit, friction-free (FR-PREFILL-5).

    The click is routed through the core boundary with the authorization flag set;
    without authorization the boundary would raise (proving the engine cannot
    self-authorize). On success an auto-sourced OutcomeEvent is recorded.
    """
    try:
        ensure_action_allowed(StepKind.FINAL_SUBMIT, engine_submit_authorized=True)
    except PrefillBoundaryViolation as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    # FR-PREFILL-5: actually CLICK the final submit (boundary-gated, authorized) before
    # recording the conversion — otherwise the real driver would mark a submission
    # without ever performing the click.
    try:
        container.browser.click_final_submit(  # type: ignore[arg-type]
            application_id, engine_submit_authorized=True
        )
    except PrefillBoundaryViolation as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    try:
        event = _record_submission(container, application_id, source=OutcomeSource.AUTO)
    except ReviewRequired as exc:
        # FR-RESUME-8: engine-finish is the highest-risk auto path; gate it hard.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    container.final_approval_service.acted(application_id)
    return {
        "application_id": application_id,
        "result": "finished_by_engine",
        "outcome_id": event.id,
    }


def _record_submission(container: Container, application_id: str, *, source: OutcomeSource):
    """Route the terminal submission through the SubmissionService (FR-LOG-1/2/4).

    Logs the application detail + archives screenshots + records the OutcomeEvent so
    both live-session paths (user-submit / engine-finish) feed conversion learning.
    """
    from applicant.app.routers.outcomes import _load_or_stub

    app = _load_or_stub(container, application_id)
    return container.submission_service.record_submission(app, source=source)
