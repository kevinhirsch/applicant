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


def _engine_error_response(exc: EngineError) -> JSONResponse:
    """Translate a typed :class:`EngineError` into a clean JSON error response.

    Transport failure (``status is None``) -> 502 (engine down/unreachable);
    otherwise pass the engine's own status through so the UI can react precisely
    (e.g. 403 boundary refusal, 404 unknown session, 409 review-required).
    """
    if exc.status is None:
        status_code = 502
        message = (
            "The live-session service timed out."
            if exc.is_timeout
            else "The live-session service is unavailable."
        )
    else:
        status_code = exc.status
        message = "The live-session service reported an error."
    return JSONResponse(
        status_code=status_code,
        content={
            "error": "engine_error",
            "message": message,
            "engine_status": exc.status,
            "detail": exc.detail,
        },
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
