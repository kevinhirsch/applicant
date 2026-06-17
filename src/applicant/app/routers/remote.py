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
from applicant.application.services.final_approval_service import (
    DECISION_ENGINE_FINISH,
    DECISION_SUBMIT_SELF,
)
from applicant.core.entities.outcome_event import OutcomeSource
from applicant.core.errors import PrefillBoundaryViolation, ReviewRequired
from applicant.core.rules.prefill_boundary import StepKind, ensure_action_allowed
from applicant.core.state_machine import ApplicationState

router = APIRouter(
    prefix="/api/remote",
    tags=["remote"],
    dependencies=[Depends(require_llm_configured)],
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


def _require_session(container: Container, session_id: str):
    """Look the session up in the sandbox registry, 404 if it doesn't exist.

    SECURITY: minting a live-session token / authorizing a takeover for an
    arbitrary, never-provisioned id would hand out a valid deep-link token for a
    session the caller never owns. Only live sessions may be acted on.
    """
    get = getattr(container.sandbox, "get", None)
    session = get(session_id) if callable(get) else None
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown sandbox session: {session_id}",
        )
    return session


@router.get("/sessions/{session_id}/view-url")
def view_url(session_id: str, container: Container = Depends(get_container)) -> dict:
    """Return the live-session URL for an existing session (FR-SANDBOX-2)."""
    _require_session(container, session_id)
    return {
        "session_id": session_id,
        "view_url": container.sandbox.remote_view().view_url(session_id),
    }


@router.post("/sessions/{session_id}/takeover", status_code=204)
def authorize_takeover(session_id: str, container: Container = Depends(get_container)) -> None:
    """Hand live control of the session to the user (FR-SANDBOX-3)."""
    _require_session(container, session_id)
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


@router.post("/applications/{application_id}/resume-account-step", status_code=200)
def resume_account_step(
    application_id: str, container: Container = Depends(get_container)
) -> dict:
    """Resume pre-fill after the user completed the human account-creation step (#4).

    An app parked at AWAITING_ACCOUNT_HUMAN_STEP (the engine never creates accounts,
    FR-PREFILL-4) is resumed via ``PrefillService.resume_after_account`` so it
    continues from where it stalled instead of restarting the whole pre-fill. The
    account-step pending action + its ping are cleared on resume (#7).
    """
    app = container.storage.applications.get(application_id)  # type: ignore[arg-type]
    if app is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown application")
    if app.status is not ApplicationState.AWAITING_ACCOUNT_HUMAN_STEP:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Application is not awaiting the account step (state={app.status.value}).",
        )
    attrs = container.storage.attributes.list_for_campaign(app.campaign_id)
    # PrefillService persists the §7 state it lands at internally; do not re-apply a
    # transition to the stale ``app`` object here (it would raise on a block state).
    result = container.prefill_service.resume_after_account(app, attrs)
    # Clear the account-step ping on resume (#7).
    try:
        container.pending_actions_service.resolve_by_dedup(
            app.campaign_id, f"account_human_step:{application_id}"
        )
        container.notification_service.acted(f"prefill:{application_id}:account_human_step")
    except Exception:  # pragma: no cover - defensive
        pass
    return {"application_id": application_id, "state": result.state.value}


@router.post("/applications/{application_id}/submit-self", status_code=201)
def submit_self(application_id: str, container: Container = Depends(get_container)) -> dict:
    """User submitted themselves in the live session (FR-PREFILL-5, FR-LOG-4).

    #1: the decision is delivered THROUGH the durable final-approval gate
    (``final_approval_service.submit_decision``) so the parked pipeline's
    submit/teardown steps run (recording the outcome, releasing capacity) instead of
    recording out-of-band and leaving the pipeline stuck at ``recv`` forever. The
    pipeline's submit step records the single OutcomeEvent — no double-recording here.
    """
    event = _deliver_decision(
        container, application_id, DECISION_SUBMIT_SELF, OutcomeSource.MANUAL
    )
    return {
        "application_id": application_id,
        "result": "submitted_by_user",
        "gate": "delivered",
        "outcome_id": event.id,
    }


@router.post("/applications/{application_id}/authorize-engine-finish", status_code=201)
def authorize_engine_finish(
    application_id: str, container: Container = Depends(get_container)
) -> dict:
    """Authorize the engine to click the final submit, friction-free (FR-PREFILL-5).

    The click is routed through the core boundary with the authorization flag set;
    without authorization the boundary would raise (proving the engine cannot
    self-authorize). #1: the decision is then delivered THROUGH the durable gate so
    the pipeline's submit/teardown steps run (one OutcomeEvent, capacity released).
    """
    try:
        ensure_action_allowed(StepKind.FINAL_SUBMIT, engine_submit_authorized=True)
    except PrefillBoundaryViolation as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    # FR-PREFILL-5: actually CLICK the final submit (boundary-gated, authorized) before
    # delivering the decision — otherwise the real driver would mark a submission
    # without ever performing the click.
    try:
        container.browser.click_final_submit(  # type: ignore[arg-type]
            application_id, engine_submit_authorized=True
        )
    except PrefillBoundaryViolation as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    event = _deliver_decision(
        container, application_id, DECISION_ENGINE_FINISH, OutcomeSource.AUTO
    )
    return {
        "application_id": application_id,
        "result": "finished_by_engine",
        "gate": "delivered",
        "outcome_id": event.id,
    }


def _deliver_decision(
    container: Container, application_id: str, decision: str, source: OutcomeSource
):
    """Deliver the user's terminal decision through the durable final-approval gate (#1).

    Two things happen, in order:

    1. ``submit_decision`` ``send``s the decision to the workflow's ``recv`` gate and
       expires the escalation ladder. A parked durable pipeline (re-driven by the
       scheduler tick) then resumes past the gate and runs its submit + teardown steps
       — so the pipeline no longer stalls at ``recv`` forever and capacity/teardown
       finally release (the bug this fixes).
    2. The terminal OutcomeEvent is recorded synchronously so the user-facing action
       is immediate. ``record_submission`` is IDEMPOTENT (IDEM-3): if the durable
       pipeline's own submit step also runs, it finds this event and returns it
       WITHOUT recording a second one — exactly one OutcomeEvent either way.

    FR-RESUME-8: ``record_submission`` enforces the review gate (``ReviewRequired`` ->
    409) so the user can never submit over unreviewed material.
    """
    from applicant.app.routers.outcomes import _load_or_stub

    app = _load_or_stub(container, application_id)
    workflow_id = f"application:{application_id}"
    container.final_approval_service.submit_decision(workflow_id, application_id, decision)
    try:
        return container.submission_service.record_submission(app, source=source)
    except ReviewRequired as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
