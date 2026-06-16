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
from applicant.app.deps import get_container, require_llm_configured
from applicant.core.entities.outcome_event import OutcomeEvent, OutcomeSource
from applicant.core.errors import PrefillBoundaryViolation
from applicant.core.ids import OutcomeEventId, new_id
from applicant.core.rules.prefill_boundary import StepKind, ensure_action_allowed

router = APIRouter(
    prefix="/api/remote", tags=["remote"], dependencies=[Depends(require_llm_configured)]
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


@router.post("/applications/{application_id}/submit-self", status_code=201)
def submit_self(application_id: str, container: Container = Depends(get_container)) -> dict:
    """User submitted themselves in the live session (FR-PREFILL-5, FR-LOG-4)."""
    event = _record_submission(container, application_id, source=OutcomeSource.MANUAL)
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
    event = _record_submission(container, application_id, source=OutcomeSource.AUTO)
    return {
        "application_id": application_id,
        "result": "finished_by_engine",
        "outcome_id": event.id,
    }


def _record_submission(container: Container, application_id: str, *, source: OutcomeSource):
    event = OutcomeEvent(
        id=OutcomeEventId(new_id()),
        application_id=application_id,  # type: ignore[arg-type]
        type="submitted",
        source=source,
    )
    container.storage.outcomes.add(event)
    container.storage.commit()
    return event
