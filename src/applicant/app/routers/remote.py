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
from applicant.app.deps import (
    get_container,
    get_pending_actions_service,
    get_post_submission_service,
    get_prefill_service,
    get_storage,
    get_submission_service,
    require_llm_configured,
)
from applicant.application.services.final_approval_service import (
    DECISION_ENGINE_FINISH,
    DECISION_SUBMIT_SELF,
)
from applicant.core.entities.outcome_event import OutcomeSource
from applicant.core.errors import ComputerUseBlocked, PrefillBoundaryViolation, ReviewRequired
from applicant.core.rules.computer_use import CaptureMode, DesktopAction
from applicant.core.rules.prefill_boundary import StepKind, ensure_action_allowed
from applicant.core.state_machine import ApplicationState
from applicant.observability.logging import get_logger

log = get_logger(__name__)

router = APIRouter(
    prefix="/api/remote",
    tags=["remote"],
    dependencies=[Depends(require_llm_configured)],
)

#: §7 states that mean "the terminal decision for this application has already been
#: delivered" — reached only via ``authorize-engine-finish``/``submit-self``.
_ALREADY_SUBMITTED_STATES = frozenset(
    {ApplicationState.SUBMITTED_BY_USER, ApplicationState.FINISHED_BY_ENGINE}
)

# Bug fix: a process-lived guard against a double-click (or the same row open in two
# tabs) delivering the SAME terminal decision twice. ``app.status`` alone can't close
# the race — both requests can read AWAITING_FINAL_APPROVAL before either finishes
# recording the decision — so this in-flight set is checked/claimed BEFORE the
# consequential work runs, mirroring the container's process-lived
# ``desktop_assist_sessions`` set (FR-CUA-4). Shared by both terminal-decision routes
# (``authorize-engine-finish`` — where a double dispatch would physically re-click the
# employer's live submit button — and ``submit-self``, audit #28: without this guard a
# double-click there still calls ``final_approval_service.submit_decision`` twice,
# ``send``-ing a second, permanently-undrained message onto the durable mailbox even
# though the resulting OutcomeEvent itself is deduped).
_finish_in_progress: set[str] = set()


class OpenSessionIn(BaseModel):
    application_id: str


@router.get("")
def index() -> dict:
    return {"surface": "remote", "phase": 2, "status": "live"}


# CRIT-auto: read-only list of the live sandbox sessions so a front-door surface
# can render a session picker for multiple concurrent takeovers (FR-SANDBOX-4).
# Uses the existing sandbox introspection (active_sessions); no new state.
@router.get("/sessions")
def list_sessions(container: Container = Depends(get_container)) -> dict:
    active = getattr(container.sandbox, "active_sessions", None)
    sessions = active() if callable(active) else []
    remote_view = container.sandbox.remote_view()
    out = []
    for s in sessions:
        out.append(
            {
                "session_id": s.session_id,
                "application_id": str(s.application_id),
                "view_url": remote_view.view_url(s.session_id),
                "has_takeover": bool(
                    getattr(remote_view, "has_takeover", lambda _sid: False)(s.session_id)
                ),
            }
        )
    return {"sessions": out, "count": len(out)}


@router.post("/sessions", status_code=201)
def open_session(body: OpenSessionIn, container: Container = Depends(get_container)) -> dict:
    """Provision a sandbox and return its one-click live-session URL (FR-SANDBOX-2).

    #11/SECURITY: provisioning hits the live sandbox control plane (e.g. neko-rooms),
    which can raise a non-:class:`DomainError` (connection refused / timeout) when the
    backend is down. A bare exception would surface as a 500; wrap it as a 503 so the
    caller learns the sandbox service is unavailable, not that the request was malformed.
    """
    from applicant.core.errors import DomainError

    try:
        session = container.sandbox.provision(body.application_id)  # type: ignore[arg-type]
    except DomainError:
        raise  # a real rule violation maps through the global handler
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Sandbox provisioning is unavailable: {exc}",
        ) from exc
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
    # #10: build the live-session link from the remote-view sub-port (which carries
    # the bound ``&app=`` continuity) instead of the pre-binding snapshot
    # ``session.remote_view_url`` (FR-SANDBOX-2/3, FR-PREFILL-5).
    url = (
        container.sandbox.remote_view().view_url(session.session_id)
        if session
        else None
    )
    handle = container.final_approval_service.request_approval(application_id, session_url=url)
    return {"application_id": application_id, "notification": handle, "gate": "awaiting"}


@router.post("/applications/{application_id}/resume-account-step", status_code=200)
def resume_account_step(
    application_id: str,
    container: Container = Depends(get_container),
    storage=Depends(get_storage),
    prefill=Depends(get_prefill_service),
    pending_actions=Depends(get_pending_actions_service),
) -> dict:
    """Resume pre-fill after the user completed the human account-creation step (#4).

    An app parked at AWAITING_ACCOUNT_HUMAN_STEP (the engine never creates accounts,
    FR-PREFILL-4) is resumed via ``PrefillService.resume_after_account`` so it
    continues from where it stalled instead of restarting the whole pre-fill. The
    account-step pending action + its ping are cleared on resume (#7).
    """
    app = storage.applications.get(application_id)  # type: ignore[arg-type]
    if app is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown application")
    if app.status is not ApplicationState.AWAITING_ACCOUNT_HUMAN_STEP:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Application is not awaiting the account step (state={app.status.value}).",
        )
    attrs = storage.attributes.list_for_campaign(app.campaign_id)
    # PrefillService persists the §7 state it lands at internally; do not re-apply a
    # transition to the stale ``app`` object here (it would raise on a block state).
    result = prefill.resume_after_account(app, attrs)
    # Clear the account-step ping on resume (#7).
    try:
        pending_actions.resolve_by_dedup(
            app.campaign_id, f"account_human_step:{application_id}"
        )
        container.notification_service.acted(f"prefill:{application_id}:account_human_step")
    except Exception:  # pragma: no cover - defensive
        pass
    # Surface the campaign + per-site key so the front-door can offer to SAVE the
    # sign-in the user just created during the account step (FR-VAULT-2). The
    # tenant_key is derived the SAME way the engine keys credentials for auto-login,
    # so a captured credential is found again next time.
    tenant_key = ""
    try:
        if app.root_url:
            from applicant.adapters.browser.ats import resolve_ats

            tenant_key = resolve_ats(app.root_url).tenant_key(app.root_url)
    except Exception:  # pragma: no cover - defensive; capture is best-effort
        tenant_key = ""
    return {
        "application_id": application_id,
        "state": result.state.value,
        "campaign_id": str(app.campaign_id),
        "tenant_key": tenant_key,
    }


@router.post("/applications/{application_id}/continue-two-factor", status_code=200)
def continue_two_factor(
    application_id: str,
    container: Container = Depends(get_container),
    storage=Depends(get_storage),
    prefill=Depends(get_prefill_service),
    pending_actions=Depends(get_pending_actions_service),
) -> dict:
    """Continue a Google 2FA hand-off (the link the notification carries).

    Triggers the 2FA push and waits up to 60s for the user's on-device approval
    (``PrefillService.resume_two_factor``). On approval the app proceeds into the form
    and the 2FA pending action + ping are cleared; on timeout the app stays held and a
    retry notification is emitted (ADR-0004 / FR-PREFILL)."""
    app = storage.applications.get(application_id)  # type: ignore[arg-type]
    if app is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown application")
    if app.status is not ApplicationState.AWAITING_ACCOUNT_HUMAN_STEP:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Application is not awaiting the account step (state={app.status.value}).",
        )
    attrs = storage.attributes.list_for_campaign(app.campaign_id)
    result = prefill.resume_two_factor(app, attrs)
    # Approved + continued (state moved off the account-step) → clear the 2FA action.
    if result.state is not ApplicationState.AWAITING_ACCOUNT_HUMAN_STEP:
        try:
            for action in pending_actions.list_pending(app.campaign_id):
                if action.kind == "two_factor" and str(
                    getattr(action, "application_id", "")
                ) == application_id:
                    pending_actions.resolve(action.id)
            container.notification_service.acted(f"prefill:{application_id}:two_factor")
        except Exception:  # pragma: no cover - defensive
            pass
    return {"application_id": application_id, "state": result.state.value}


@router.post("/applications/{application_id}/resume-detection-step", status_code=200)
def resume_detection_step(
    application_id: str,
    container: Container = Depends(get_container),
    storage=Depends(get_storage),
    prefill=Depends(get_prefill_service),
    pending_actions=Depends(get_pending_actions_service),
) -> dict:
    """Resume pre-fill after the user cleared a detection challenge (#2, FR-PREFILL-6).

    An app parked at BLOCKED_DETECTION is resumed via
    ``PrefillService.resume_after_detection`` — a LEGAL BLOCKED_DETECTION -> PREFILLING
    transition (§7). The old re-drive routed through the full-restart pre-fill (whose
    first move is SANDBOX_PROVISIONING) which raised IllegalStateTransition and left the
    app stranded with no resolver. The detection-blocker pending action + its ping are
    cleared on resume (#7); the live session the user just cleared is NOT torn down.
    """
    app = storage.applications.get(application_id)  # type: ignore[arg-type]
    if app is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown application")
    if app.status is not ApplicationState.BLOCKED_DETECTION:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Application is not blocked on detection (state={app.status.value}).",
        )
    attrs = storage.attributes.list_for_campaign(app.campaign_id)
    result = prefill.resume_after_detection(app, attrs, cautious=False)
    try:
        pending_actions.resolve_by_dedup(
            app.campaign_id, f"detection_blocker:{application_id}"
        )
        container.notification_service.acted(f"prefill:{application_id}:detection_blocker")
    except Exception:  # pragma: no cover - defensive
        pass
    return {"application_id": application_id, "state": result.state.value}


#: Pending-action kinds that carry an emergency copy/paste handoff payload
#: (FR-PREFILL-7): a hard fill failure (``PrefillService.emergency_handoff``) and
#: a near-empty "wrong ATS" fill (``flag_probable_wrong_ats``, #177) — both land
#: EMERGENCY_DATA_HANDOFF via the same value-assembly + transition.
_HANDOFF_KINDS = frozenset({"emergency_handoff", "wrong_ats"})


@router.get("/applications/{application_id}/emergency-handoff")
def get_emergency_handoff(
    application_id: str,
    storage=Depends(get_storage),
) -> dict:
    """The emergency copy/paste handoff values for an application (FR-PREFILL-7).

    Meaningful once pre-fill reported it tried to fill the form and failed and the
    application landed ``EMERGENCY_DATA_HANDOFF`` — a hard fill failure or a
    near-empty "wrong ATS" fill (#177), both routed through
    ``PrefillService.emergency_handoff``. Returns the values the agent WOULD have
    filled, for the user to paste into their own browser and finish the
    application by hand, alongside the open pending action's title so the
    takeover UI can render one panel. ``available: False`` (never a 404) when
    there is no open handoff for this application — the panel simply stays
    hidden rather than erroring, since a caller may poll this during any
    live-takeover session.
    """
    app = storage.applications.get(application_id)  # type: ignore[arg-type]
    if app is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown application")
    action = None
    for candidate in storage.pending_actions.list_open(app.campaign_id):
        if (
            str(getattr(candidate, "application_id", "")) == application_id
            and candidate.kind in _HANDOFF_KINDS
        ):
            action = candidate
            break
    if action is None:
        return {
            "application_id": application_id,
            "state": app.status.value,
            "available": False,
            "handoff_values": {},
        }
    payload = action.payload or {}
    return {
        "application_id": application_id,
        "state": app.status.value,
        "available": True,
        "kind": action.kind,
        "title": action.title,
        "handoff_values": payload.get("handoff_values", {}),
        "session_url": payload.get("session_url"),
        "match_rate_pct": payload.get("match_rate_pct"),
    }


@router.post("/applications/{application_id}/submit-self", status_code=201)
def submit_self(
    application_id: str,
    container: Container = Depends(get_container),
    storage=Depends(get_storage),
    submission=Depends(get_submission_service),
    post_submission=Depends(get_post_submission_service),
) -> dict:
    """User submitted themselves in the live session (FR-PREFILL-5, FR-LOG-4).

    #1: the decision is delivered THROUGH the durable final-approval gate
    (``final_approval_service.submit_decision``) so the parked pipeline's
    submit/teardown steps run (recording the outcome, releasing capacity) instead of
    recording out-of-band and leaving the pipeline stuck at ``recv`` forever. The
    pipeline's submit step records the single OutcomeEvent — no double-recording here.

    Audit #28: guarded the same way as ``authorize-engine-finish`` — a state check
    (already-terminal -> 409) plus the shared in-flight lock BEFORE
    ``_deliver_decision`` — so a double-click / two-tab race can't deliver the
    decision twice. ``record_submission`` already dedupes the resulting OutcomeEvent,
    but without this guard each duplicate call still ``send``s a second message onto
    the durable final-approval mailbox that nothing will ever drain.
    """
    # An outcome can only be recorded for a real application; a bogus/stale id would
    # otherwise hit a foreign-key IntegrityError (-> 500) at record_submission on a real
    # DB. Fail cleanly with 404, mirroring resume-account/resume-detection.
    app = storage.applications.get(application_id)  # type: ignore[arg-type]
    if app is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown application")
    if app.status in _ALREADY_SUBMITTED_STATES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This application has already been submitted.",
        )
    if application_id in _finish_in_progress:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This application is already being submitted.",
        )
    _finish_in_progress.add(application_id)
    try:
        event = _deliver_decision(
            container,
            storage,
            submission,
            application_id,
            DECISION_SUBMIT_SELF,
            OutcomeSource.MANUAL,
            post_submission=post_submission,
        )
    finally:
        _finish_in_progress.discard(application_id)
    return {
        "application_id": application_id,
        "result": "submitted_by_user",
        "gate": "delivered",
        "outcome_id": event.id,
    }


@router.post("/applications/{application_id}/authorize-engine-finish", status_code=201)
def authorize_engine_finish(
    application_id: str,
    container: Container = Depends(get_container),
    storage=Depends(get_storage),
    submission=Depends(get_submission_service),
    post_submission=Depends(get_post_submission_service),
) -> dict:
    """Authorize the engine to click the final submit, friction-free (FR-PREFILL-5).

    The click is routed through the core boundary with the authorization flag set;
    without authorization the boundary would raise (proving the engine cannot
    self-authorize). #1: the decision is then delivered THROUGH the durable gate so
    the pipeline's submit/teardown steps run (one OutcomeEvent, capacity released).
    """
    # Reject a bogus/stale application id up front (404) before touching the browser
    # or the durable gate — recording an outcome for a non-existent app would FK-crash
    # (-> 500) at record_submission on a real DB. Mirrors the other handoff endpoints.
    app = storage.applications.get(application_id)  # type: ignore[arg-type]
    if app is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown application")
    # Bug fix: state-guard BEFORE the click. A prior decision already landed for this
    # application (e.g. the first of two rapid clicks already finished) — never click
    # the employer's real submit button again.
    if app.status in _ALREADY_SUBMITTED_STATES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This application has already been submitted.",
        )
    # Bug fix: claim the in-flight guard before the click so a second, near-simultaneous
    # request (double-click / the same row open in two tabs) can't race the state check
    # above and click a second time while the first click is still in flight.
    if application_id in _finish_in_progress:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This application is already being submitted.",
        )
    _finish_in_progress.add(application_id)
    try:
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
            container,
            storage,
            submission,
            application_id,
            DECISION_ENGINE_FINISH,
            OutcomeSource.AUTO,
            post_submission=post_submission,
        )
    finally:
        _finish_in_progress.discard(application_id)
    return {
        "application_id": application_id,
        "result": "finished_by_engine",
        "gate": "delivered",
        "outcome_id": event.id,
    }


def _deliver_decision(
    container: Container,
    storage,
    submission,
    application_id: str,
    decision: str,
    source: OutcomeSource,
    *,
    post_submission=None,
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
    3. Dark-engine audit item 12: once the terminal state (SUBMITTED_BY_USER /
       FINISHED_BY_ENGINE) is durably recorded, advance the application into
       ``PostSubmissionService.enter_post_submission`` so it actually *enters*
       the G16 lifecycle (POST_SUBMISSION) instead of sitting in a state the
       ghosting sweep / awaiting-response bucket never look at.
       ``SubmissionService.record_submission`` deliberately does NOT call this
       itself (it would break the mark-submitted contract used by the
       admin/outcomes one-tap path — see its own docstring), so this is wired
       here at the ONE real "the user is done, hand it to the tracker" call
       site instead. Best-effort: a failure here must never undo the terminal
       submission that was just recorded.

    FR-RESUME-8: ``record_submission`` enforces the review gate (``ReviewRequired`` ->
    409) so the user can never submit over unreviewed material.
    """
    from applicant.app.routers.outcomes import _load_or_stub

    app = _load_or_stub(storage, application_id)
    workflow_id = f"application:{application_id}"
    container.final_approval_service.submit_decision(workflow_id, application_id, decision)
    try:
        event = submission.record_submission(app, source=source)
    except ReviewRequired as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if post_submission is not None:
        try:
            terminal_app = storage.applications.get(application_id)
            if terminal_app is not None:
                post_submission.enter_post_submission(terminal_app)
        except Exception:  # pragma: no cover - defensive: never undo a delivered submission
            log.warning(
                "enter_post_submission_failed", application_id=str(application_id), exc_info=True
            )
    return event


# ── Desktop assist (FR-CUA) ──────────────────────────────────────────────────
#
# An OPT-IN, per-session, revocable layer that lets the assistant help on the
# desktop (native file pickers / OS dialogs the browser can't reach) DURING an
# open live session, complementing — never replacing — browser pre-fill. It ships
# DORMANT (FR-CUA-9): wired present-but-grayed until the desktop driver + its
# display stack are baked into the sandbox image and the health preflight passes.
#
# Safety (no new bypass):
#   * Every destructive action goes through the ComputerUsePort adapter, which
#     calls the pure core guards (hard-blocks FR-CUA-5, no-secrets FR-CUA-6,
#     stop-boundary FR-CUA-3) before any side effect — this router adds no path
#     around them. ``capture`` is the only read-only action.
#   * The engine still cannot self-authorize a final submit (FR-CUA-3): a desktop
#     action whose intent maps to a boundary step is denied exactly as the browser
#     path is. There is no caller flag that opts past the boundary.
#   * Desktop assist must be enabled for the live session first (opt-in, FR-CUA-4),
#     and the backend must be healthy — otherwise actions are refused.


class DesktopActionIn(BaseModel):
    """A guarded desktop-assist action request (FR-CUA, spec §4).

    ``intent`` is a control LABEL the caller derived from the targeted element; the
    core maps it to a boundary step server-side (it is NOT a bypass — there is no
    flag that opts past the stop-boundary, FR-CUA-3).
    """

    action: str
    element_token: str = ""
    text: str = ""
    keys: str = ""
    app: str = ""
    intent: str | None = None
    mode: str = "som"


def _desktop_health(container: Container) -> dict:
    """The desktop-assist preflight, as a plain dict (FR-CUA-12).

    Operability is CAPABILITY-gated, not flag-gated: the control is operable only when a
    *real* desktop driver answered the health preflight (``ok``) AND the active backend
    is not the ``noop`` test backend. So a default ``COMPUTER_USE_BACKEND=noop`` deploy —
    or a ``cua`` backend whose driver binary isn't baked into the sandbox image — reports
    ``available: false`` and the front door renders the control locked, honestly. The
    surface is wired LIVE; what gates it is the presence of a working driver, not a static
    dormancy flag (``dormant`` is retained for back-compat / observability only)."""
    report = container.computer_use.health()
    available = bool(report.ok) and report.backend != "noop"
    return {
        "available": available,
        # Back-compat field: true only while NO real desktop driver is operable.
        "dormant": not available,
        "ok": bool(report.ok),
        "backend": report.backend,
        "detail": report.detail,
        "missing": list(report.missing),
    }


@router.get("/desktop/health")
def desktop_health(container: Container = Depends(get_container)) -> dict:
    """Desktop-assist preflight: is the driver present + the surface live? (FR-CUA-12).

    A failure here is a DEPLOY/IMAGE signal (the desktop driver or its display stack
    is not baked into the sandbox image) — not a per-request error. The front door
    greys the control honestly off this.
    """
    return _desktop_health(container)


@router.get("/sessions/{session_id}/desktop")
def desktop_state(session_id: str, container: Container = Depends(get_container)) -> dict:
    """Whether desktop assist is opted-in for this live session (FR-CUA-4)."""
    _require_session(container, session_id)
    enabled = session_id in container.desktop_assist_sessions
    return {"session_id": session_id, "enabled": enabled, **_desktop_health(container)}


@router.post("/sessions/{session_id}/desktop/enable", status_code=200)
def desktop_enable(session_id: str, container: Container = Depends(get_container)) -> dict:
    """Opt this live session in to desktop assist (FR-CUA-4 — opt-in, revocable).

    Refused (409) while the surface is dormant / the driver is missing, so the user
    never enables a capability that would silently do nothing.
    """
    _require_session(container, session_id)
    health = _desktop_health(container)
    if not health["available"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Desktop assist isn't available yet on this sandbox. It will be "
                "offered in a future update once the desktop helper is set up."
            ),
        )
    container.desktop_assist_sessions.add(session_id)
    return {"session_id": session_id, "enabled": True, **health}


@router.post("/sessions/{session_id}/desktop/disable", status_code=200)
def desktop_disable(session_id: str, container: Container = Depends(get_container)) -> dict:
    """Revoke desktop assist for this live session (FR-CUA-4 — always allowed)."""
    _require_session(container, session_id)
    container.desktop_assist_sessions.discard(session_id)
    return {"session_id": session_id, "enabled": False}


@router.post("/sessions/{session_id}/desktop/action", status_code=200)
def desktop_action(
    session_id: str,
    body: DesktopActionIn,
    container: Container = Depends(get_container),
) -> dict:
    """Perform a single bounded desktop action behind approval (FR-CUA-4/3/5/6).

    Guarded passthrough to the ``ComputerUsePort`` adapter, which enforces the core
    guards (hard-blocks, no-secrets, stop-boundary) BEFORE any side effect — this
    route adds no bypass. Refused (409) unless desktop assist is opted-in for the
    session and the backend is healthy.
    """
    _require_session(container, session_id)
    if session_id not in container.desktop_assist_sessions:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Turn on desktop assist for this session first.",
        )
    if not _desktop_health(container)["available"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Desktop assist isn't available on this sandbox.",
        )

    try:
        action = DesktopAction(body.action.strip().lower())
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown desktop action: {body.action!r}",
        ) from exc

    cu = container.computer_use
    # Each branch calls the adapter, which calls the pure core guards first. A
    # blocked/boundary action raises ``ComputerUseBlocked``/``PrefillBoundaryViolation``
    # — surfaced as a clean 4xx, never bypassed.
    try:
        if action is DesktopAction.CAPTURE:
            mode = CaptureMode.AX if body.mode.strip().lower() == "ax" else CaptureMode.SOM
            cap = cu.capture(mode)
            return {
                "session_id": session_id,
                "action": action.value,
                "mode": cap.mode.value,
                "element_count": cap.element_count,
                # Never echo the raw screenshot payload back through the proxy.
                "has_image": bool(cap.image_b64),
                "has_ax_tree": bool(cap.ax_tree),
            }
        if action is DesktopAction.CLICK:
            res = cu.click(body.element_token, intent=body.intent)
        elif action is DesktopAction.TYPE_TEXT:
            res = cu.type_text(body.text, intent=body.intent)
        elif action is DesktopAction.KEY:
            res = cu.key(body.keys, intent=body.intent)
        elif action is DesktopAction.SCROLL:
            res = cu.scroll(body.element_token)
        elif action is DesktopAction.DRAG:
            res = cu.drag(body.element_token, body.app)
        else:  # FOCUS_APP
            res = cu.focus_app(body.app)
    except ComputerUseBlocked:
        raise  # -> 400 via the global domain-error handler (honest refusal)
    except PrefillBoundaryViolation as exc:  # stop-boundary: cannot submit/create acct
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return {
        "session_id": session_id,
        "action": res.action.value,
        "performed": res.performed,
        "detail": res.detail,
    }
