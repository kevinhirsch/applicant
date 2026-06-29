# routes/applicant_remote_routes.py
"""Applicant LIVE-SESSION proxy — the workspace-side endpoints the "Watch / Take
over live session" surface calls to view a running browser session, take live
control, and finish an application.

This is the automation/security front-door for the engine's ``remote`` router
(FR-SANDBOX-2/3/4, FR-PREFILL-5). It is a thin, auth-protected, owner-scoped
proxy in front of :class:`src.applicant_engine.ApplicantEngineClient`; every
handler maps 1:1 to an engine endpoint and hands back the engine's JSON
unchanged so the front-end renders the same shapes the engine produces.

Security notes (the load-bearing part of this surface):

* **The engine never self-authorizes the final submit.** The two terminal
  controls — *submit yourself* and *authorize the engine to finish* — call the
  engine's EXPLICIT authorize endpoints (``/submit-self`` /
  ``/authorize-engine-finish``). The authorize endpoint routes the click through
  the core pre-fill stop-boundary with the authorization flag set; without the
  user's explicit action the boundary raises and the engine returns 403. This
  proxy adds no path that bypasses that boundary.
* **Owner-scoped + auth-gated.** Every route requires an authenticated session
  (``require_user``). The mutating controls (take over, submit, authorize,
  resume) additionally require ``can_use_documents`` — the same privilege that
  gates driving the owner's real application materials — so a restricted account
  cannot drive a live submission through the proxy.
* **No secrets logged.** Nothing here logs request bodies; the live-session URL
  is minted (and TTL'd) by the engine and only passed through.

Graceful degradation mirrors the other Applicant proxies: a typed
:class:`EngineError` becomes a clean JSON error (502 when the engine is
unreachable, otherwise the engine's own status) instead of a 500 + traceback.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from src.applicant_engine import ApplicantEngineClient, EngineError
from src.auth_helpers import require_privilege, require_user

logger = logging.getLogger(__name__)


class OpenSessionIn(BaseModel):
    """Open a live session for an application (provisions a sandbox)."""

    application_id: str


class DesktopActionIn(BaseModel):
    """A guarded desktop-assist action (FR-CUA). Mirrors the engine's request shape.

    ``intent`` is a control LABEL the caller derived from the targeted element; the
    engine core maps it to a boundary step server-side — it is NOT a bypass (no flag
    can opt a desktop action past the stop-boundary, FR-CUA-3).
    """

    action: str
    element_token: str = ""
    text: str = ""
    keys: str = ""
    app: str = ""
    intent: str | None = None
    mode: str = "som"


def _engine_error_response(exc: EngineError) -> JSONResponse:
    """Translate a typed :class:`EngineError` into a clean JSON error response.

    Transport failure (``status is None``) -> 502 (engine down/unreachable).
    4xx responses are forwarded (client-correctable: 403 boundary refusal, 404
    unknown session, 409 review-required). 5xx responses are scrubbed — raw
    detail may contain internal stack traces; logged server-side only.
    """
    if exc.status is None:
        message = (
            "The live-session service timed out."
            if exc.is_timeout
            else "The live-session service is unavailable."
        )
        return JSONResponse(
            status_code=502,
            content={"error": "engine_error", "message": message, "engine_status": None},
        )
    if exc.status >= 500:
        logger.warning("engine 5xx (remote): status=%s detail=%s", exc.status, exc.detail or exc.message)
        return JSONResponse(
            status_code=502,
            content={"error": "engine_error", "message": "The live-session service reported an error.", "engine_status": exc.status},
        )
    return JSONResponse(
        status_code=exc.status,
        content={"error": "engine_error", "message": "The live-session service reported an error.", "engine_status": exc.status},
    )


def setup_applicant_remote_routes() -> APIRouter:
    """Build the Applicant live-session proxy router (mounted in ``app.py``)."""
    router = APIRouter(prefix="/api/applicant/remote", tags=["applicant-remote"])

    # ── session listing / opening ───────────────────────────────────────

    @router.get("/sessions")
    async def list_sessions(request: Request) -> JSONResponse:
        """All currently live sessions, for the session picker
        (engine ``GET /api/remote/sessions``)."""
        require_user(request)
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.list_remote_sessions()
        except EngineError as exc:
            logger.info("applicant remote sessions unavailable: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data or {"sessions": [], "count": 0})

    @router.post("/sessions")
    async def open_session(body: OpenSessionIn, request: Request) -> JSONResponse:
        """Provision a sandbox for an application and return its one-click view URL
        (engine ``POST /api/remote/sessions``)."""
        require_privilege(request, "can_use_documents")
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.open_remote_session(body.application_id)
        except EngineError as exc:
            logger.info("applicant remote open-session failed: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data, status_code=201)

    @router.get("/sessions/{session_id}/view-url")
    async def view_url(session_id: str, request: Request) -> JSONResponse:
        """The token-bearing live-session URL for an existing session — embedded
        in the viewer iframe (engine ``GET /api/remote/sessions/{id}/view-url``)."""
        require_user(request)
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.remote_session_view_url(session_id)
        except EngineError as exc:
            logger.info("applicant remote view-url unavailable: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data)

    @router.post("/sessions/{session_id}/takeover")
    async def takeover(session_id: str, request: Request) -> JSONResponse:
        """Hand live control of the session to the user
        (engine ``POST /api/remote/sessions/{id}/takeover``)."""
        require_privilege(request, "can_use_documents")
        try:
            async with ApplicantEngineClient() as engine:
                await engine.takeover_remote_session(session_id)
        except EngineError as exc:
            logger.info("applicant remote takeover failed: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content={"session_id": session_id, "takeover": "granted"})

    # ── final-submit / authorize (THE stop-boundary controls) ───────────

    @router.post("/applications/{application_id}/request-final-approval")
    async def request_final_approval(application_id: str, request: Request) -> JSONResponse:
        """Notify the user an application awaits final approval
        (engine ``POST /api/remote/applications/{id}/request-final-approval``)."""
        require_privilege(request, "can_use_documents")
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.request_final_approval(application_id)
        except EngineError as exc:
            logger.info("applicant remote request-final-approval failed: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data, status_code=202)

    @router.post("/applications/{application_id}/submit-self")
    async def submit_self(application_id: str, request: Request) -> JSONResponse:
        """The user submitted the application themselves in the live session
        (engine ``POST /api/remote/applications/{id}/submit-self``). Terminal."""
        require_privilege(request, "can_use_documents")
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.submit_self(application_id)
        except EngineError as exc:
            logger.info("applicant remote submit-self failed: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data, status_code=201)

    @router.post("/applications/{application_id}/authorize-engine-finish")
    async def authorize_engine_finish(application_id: str, request: Request) -> JSONResponse:
        """Explicitly authorize the engine to click the final submit
        (engine ``POST /api/remote/applications/{id}/authorize-engine-finish``).

        SECURITY: this is the ONLY path that lets the engine perform the final
        click, and it is the user's explicit action. The engine routes the click
        through the core stop-boundary with the authorization flag set; absent
        this call the boundary refuses and the engine returns 403. Terminal.
        """
        require_privilege(request, "can_use_documents")
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.authorize_engine_finish(application_id)
        except EngineError as exc:
            logger.info("applicant remote authorize-engine-finish failed: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data, status_code=201)

    # ── resume after a human-only step ──────────────────────────────────

    @router.post("/applications/{application_id}/resume-account-step")
    async def resume_account_step(application_id: str, request: Request) -> JSONResponse:
        """Resume after the user completed the human account-creation step
        (engine ``POST /api/remote/applications/{id}/resume-account-step``)."""
        require_privilege(request, "can_use_documents")
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.resume_account_step(application_id)
        except EngineError as exc:
            logger.info("applicant remote resume-account-step failed: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data)

    @router.post("/applications/{application_id}/resume-detection-step")
    async def resume_detection_step(application_id: str, request: Request) -> JSONResponse:
        """Resume after the user cleared a detection challenge
        (engine ``POST /api/remote/applications/{id}/resume-detection-step``)."""
        require_privilege(request, "can_use_documents")
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.resume_detection_step(application_id)
        except EngineError as exc:
            logger.info("applicant remote resume-detection-step failed: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data)

    @router.post("/applications/{application_id}/continue-two-factor")
    async def continue_two_factor(application_id: str, request: Request) -> JSONResponse:
        """Continue a Google 2FA hand-off — the link the notification carries. Triggers
        the push and waits up to 60s for on-device approval; on approval pre-fill
        continues, on timeout the engine re-notifies for a retry
        (engine ``POST /api/remote/applications/{id}/continue-two-factor``)."""
        require_privilege(request, "can_use_documents")
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.continue_two_factor(application_id)
        except EngineError as exc:
            logger.info("applicant remote continue-two-factor failed: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data)

    # ── desktop assist (FR-CUA): opt-in, per-session, ships DORMANT ──────
    #
    # Thin owner-scoped proxies over the engine's desktop-assist endpoints. The
    # capability ships present-but-grayed until the desktop helper is baked into
    # the sandbox image and the health preflight passes; the read proxies degrade
    # cleanly (honest disabled state) rather than 500ing. Reads are auth-only; the
    # mutating controls require ``can_use_documents`` like the other live-session
    # controls. The destructive-action passthrough adds NO bypass — the engine
    # enforces its core safety gates (the engine cannot self-authorize a final
    # submit), and a typed boundary refusal (403) passes straight through.

    @router.get("/desktop/health")
    async def desktop_health(request: Request) -> JSONResponse:
        """Is desktop assist available on this sandbox yet? (honest disabled state)."""
        require_user(request)
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.desktop_assist_health()
        except EngineError as exc:
            logger.info("applicant desktop-assist health unavailable: %s", exc)
            # Degrade to an honest disabled state — never block the surface.
            return JSONResponse(content={"available": False, "dormant": True, "ok": False})
        return JSONResponse(content=data or {"available": False, "dormant": True})

    @router.get("/sessions/{session_id}/desktop")
    async def desktop_state(session_id: str, request: Request) -> JSONResponse:
        """Whether desktop assist is opted-in for this live session (+ health)."""
        require_user(request)
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.desktop_assist_state(session_id)
        except EngineError as exc:
            logger.info("applicant desktop-assist state unavailable: %s", exc)
            return JSONResponse(
                content={
                    "session_id": session_id,
                    "enabled": False,
                    "available": False,
                    "dormant": True,
                }
            )
        return JSONResponse(content=data)

    @router.post("/sessions/{session_id}/desktop/enable")
    async def desktop_enable(session_id: str, request: Request) -> JSONResponse:
        """Opt this live session in to desktop assist (engine refuses while dormant)."""
        require_privilege(request, "can_use_documents")
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.desktop_assist_enable(session_id)
        except EngineError as exc:
            logger.info("applicant desktop-assist enable failed: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data)

    @router.post("/sessions/{session_id}/desktop/disable")
    async def desktop_disable(session_id: str, request: Request) -> JSONResponse:
        """Revoke desktop assist for this live session."""
        require_privilege(request, "can_use_documents")
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.desktop_assist_disable(session_id)
        except EngineError as exc:
            logger.info("applicant desktop-assist disable failed: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data)

    @router.post("/sessions/{session_id}/desktop/action")
    async def desktop_action(
        session_id: str, body: DesktopActionIn, request: Request
    ) -> JSONResponse:
        """Perform a single guarded desktop action (engine enforces the safety gates)."""
        require_privilege(request, "can_use_documents")
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.desktop_assist_action(
                    session_id, body.model_dump(exclude_none=True)
                )
        except EngineError as exc:
            logger.info("applicant desktop-assist action failed: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data)

    # ── honesty caveat (best-effort / egress) ───────────────────────────

    @router.get("/caveat")
    async def caveat(request: Request) -> JSONResponse:
        """The honest best-effort anti-detection + egress caveat copy shown near
        the takeover surface (engine ``GET /api/admin/stealth``)."""
        require_user(request)
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.stealth_caveat()
        except EngineError as exc:
            logger.info("applicant stealth caveat unavailable: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data)

    return router
