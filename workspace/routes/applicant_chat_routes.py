# routes/applicant_chat_routes.py
"""Applicant Chat/Agent ↔ engine bridge (Stage-2 Lane C).

The workspace's *Job Assistant* surface talks to the Applicant **engine**
(`http://api:8000`) through these endpoints. They are thin, auth-protected
proxies over :class:`src.applicant_engine.ApplicantEngineClient`: the browser
never reaches the engine directly, and every engine failure is normalised to a
clean HTTP response so the chat surface degrades gracefully instead of throwing.

What the surface needs (all backed 1:1 by an engine endpoint group):

* **Assistant chat** — send a conversational turn (``POST /api/chat``) and commit
  a confirmation-gated change (``POST /api/chat/confirm``).
* **Pending job actions** — list everything awaiting the user for a campaign
  (``GET /api/pending-actions/{id}``) and resolve one (``POST .../resolve``).
* **Campaign state** — list campaigns / create one
  (``GET`` / ``POST /api/campaigns``) so the surface can pick a working campaign.
* **Safe job actions** — the user-driven, non-destructive remote actions the
  engine already exposes: request a final-approval ping, and resume a run that is
  parked on a human account-creation step or a cleared detection challenge
  (``POST /api/remote/applications/{id}/...``).

This file is **additive** and disjoint from the workspace's own native chat /
assistant surfaces (``chat_routes.py`` / ``assistant_routes.py``): it mounts a
separate ``/api/applicant/chat`` prefix and leaves those untouched.

Design notes:

* Auth: these routes are NOT in the auth-exempt list, so the global auth gate in
  ``app.py`` requires a logged-in session — correct for job-engine actions.
* Errors: a transport failure (engine down / timeout) → 503; an engine HTTP
  error is surfaced with its own status (e.g. 409 ``review required`` passes
  through) so the UI can show the engine's own message. No raw httpx escapes —
  the engine client guarantees a typed :class:`EngineError`.
* ``GET`` listings degrade *soft*: if the engine is unreachable they return an
  empty, well-formed payload with ``engine_available: false`` rather than 5xx,
  so the panel can render its "connect the engine" empty state.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from src.applicant_engine import ApplicantEngineClient, EngineError
from src.auth_helpers import get_current_user

logger = logging.getLogger(__name__)


# --- request bodies ---------------------------------------------------------


class ChatIn(BaseModel):
    campaign_id: str
    message: str


class ConfirmIn(BaseModel):
    campaign_id: str
    name: str
    value: str


class CreateCampaignIn(BaseModel):
    name: str


# --- helpers ----------------------------------------------------------------


def _require_user(request: Request) -> str:
    """Require an authenticated owner (the global gate also enforces this)."""
    owner = get_current_user(request)
    if not owner:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return owner


def _engine_http_error(exc: EngineError) -> HTTPException:
    """Translate a typed :class:`EngineError` into an HTTPException for a *write*.

    A transport-level failure (timeout / connection refused — no response) means
    the engine is unreachable → 503. 4xx responses from the engine are forwarded
    (client-correctable: 409 review-required gate, 422 validation). 5xx responses
    are scrubbed — the raw detail may contain internal stack traces or state; we
    log it server-side and return a generic message to the browser.
    """
    if exc.status is None:
        return HTTPException(
            status_code=503,
            detail="The Applicant engine is unavailable right now. Please try again shortly.",
        )
    if exc.status >= 500:
        logger.warning("engine 5xx (chat): status=%s detail=%s", exc.status, exc.detail or exc.message)
        return HTTPException(status_code=502, detail="The Applicant engine returned an error.")
    detail = exc.detail if exc.detail not in (None, "") else exc.message
    return HTTPException(status_code=exc.status, detail=detail)


_SAFE_CHANGE_KEYS = frozenset(
    {"kind", "name", "value", "is_integral", "is_sensitive", "requires_confirmation", "applied"}
)


def _scrub_chat_reply(raw: dict) -> dict:
    """Whitelist the engine's chat reply to only user-facing fields.

    The engine may include ``control_actions`` (internal agent-loop orchestration
    state that can carry run IDs and internal session handles) and other fields
    that are not needed by and must not be forwarded to the browser.
    """
    changes = []
    for c in raw.get("proposed_changes") or []:
        if isinstance(c, dict):
            changes.append({k: v for k, v in c.items() if k in _SAFE_CHANGE_KEYS})
    return {
        "message": raw.get("message") or "",
        "gaps": [g for g in (raw.get("gaps") or []) if isinstance(g, str)],
        "proposed_changes": changes,
    }


def _scrub_confirm_reply(raw: dict) -> dict:
    """Whitelist the engine's confirm reply to only user-facing fields."""
    return {
        "committed": bool(raw.get("committed")),
        "name": raw.get("name") or "",
        "value": raw.get("value") or "",
    }


def setup_applicant_chat_routes() -> APIRouter:
    router = APIRouter(prefix="/api/applicant/chat", tags=["applicant-chat"])

    # -- status -----------------------------------------------------------

    @router.get("/status")
    async def status(request: Request) -> dict:
        """Lightweight reachability probe for the Job Assistant surface.

        Lets the panel decide whether to show the live chat or the "connect a
        model to activate" empty state without firing a full chat turn.
        """
        _require_user(request)
        async with ApplicantEngineClient() as engine:
            available = await engine.engine_available()
        return {"engine_available": available}

    # -- campaigns --------------------------------------------------------

    @router.get("/campaigns")
    async def list_campaigns(request: Request) -> dict:
        """List the engine's campaigns so the surface can pick a working one.

        Degrades soft: an unreachable engine returns an empty list rather than
        5xx, so the panel renders its empty state.
        """
        _require_user(request)
        async with ApplicantEngineClient() as engine:
            try:
                campaigns = await engine.list_campaigns()
            except EngineError as exc:
                logger.debug("list_campaigns: engine unavailable: %s", exc)
                return {"engine_available": False, "campaigns": []}
        return {"engine_available": True, "campaigns": campaigns or []}

    @router.post("/campaigns")
    async def create_campaign(body: CreateCampaignIn, request: Request) -> dict:
        """Create a campaign on the engine (used to bootstrap a first workspace)."""
        _require_user(request)
        name = (body.name or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="Campaign name is required")
        async with ApplicantEngineClient() as engine:
            try:
                created = await engine.create_campaign(name)
            except EngineError as exc:
                raise _engine_http_error(exc) from exc
        return created or {}

    # -- assistant chat ---------------------------------------------------

    @router.post("/message")
    async def send_message(body: ChatIn, request: Request) -> dict:
        """Send one conversational turn to the engine assistant.

        Returns the reply, identified gaps, and any proposed attribute/criteria
        changes. Integral/sensitive proposals carry ``requires_confirmation`` and
        are NOT auto-applied — the surface confirms them via ``/confirm``.
        """
        _require_user(request)
        if not (body.message or "").strip():
            raise HTTPException(status_code=400, detail="Message is required")
        if not (body.campaign_id or "").strip():
            raise HTTPException(status_code=400, detail="A campaign is required")
        async with ApplicantEngineClient() as engine:
            try:
                result = await engine.chat(
                    {"campaign_id": body.campaign_id, "message": body.message}
                )
            except EngineError as exc:
                raise _engine_http_error(exc) from exc
        return _scrub_chat_reply(result or {})

    @router.post("/confirm")
    async def confirm_change(body: ConfirmIn, request: Request) -> dict:
        """Commit a confirmation-gated change the user explicitly approved."""
        _require_user(request)
        async with ApplicantEngineClient() as engine:
            try:
                result = await engine.chat_confirm(
                    {
                        "campaign_id": body.campaign_id,
                        "name": body.name,
                        "value": body.value,
                    }
                )
            except EngineError as exc:
                raise _engine_http_error(exc) from exc
        return _scrub_confirm_reply(result or {})

    # -- pending job actions ----------------------------------------------

    @router.get("/pending-actions/{campaign_id}")
    async def list_pending_actions(campaign_id: str, request: Request) -> dict:
        """List open job actions awaiting the user for a campaign.

        Degrades soft (empty list) when the engine is unreachable so the surface
        can keep rendering the conversation.
        """
        _require_user(request)
        async with ApplicantEngineClient() as engine:
            try:
                data = await engine.list_pending_actions(campaign_id)
            except EngineError as exc:
                logger.debug("list_pending_actions: engine unavailable: %s", exc)
                return {
                    "engine_available": False,
                    "campaign_id": campaign_id,
                    "count": 0,
                    "items": [],
                }
        # The engine returns {campaign_id, count, items:[...]}; pass it through and
        # flag reachability so the client can distinguish "none" from "offline".
        out = data if isinstance(data, dict) else {"items": data or []}
        out.setdefault("campaign_id", campaign_id)
        out.setdefault("items", [])
        out.setdefault("count", len(out.get("items") or []))
        out["engine_available"] = True
        return out

    @router.post("/pending-actions/{action_id}/resolve")
    async def resolve_pending_action(action_id: str, request: Request) -> dict:
        """Resolve a pending action once the user has acted on it."""
        _require_user(request)
        async with ApplicantEngineClient() as engine:
            try:
                await engine.resolve_pending_action(action_id)
            except EngineError as exc:
                raise _engine_http_error(exc) from exc
        return {"resolved": True, "action_id": action_id}

    # -- safe job actions (remote) ----------------------------------------
    #
    # Only the user-driven, non-destructive remote actions are exposed here. The
    # engine NEVER self-authorizes the final submit (the pre-fill boundary), and
    # the destructive/terminal paths (submit-self / authorize-engine-finish /
    # takeover) are deliberately left out of the chat surface — they belong to a
    # live-session control surface, not an inline chat affordance.

    async def _remote_action(path: str) -> dict:
        """POST a safe remote job action and normalise failures.

        The shared engine client (``applicant_engine.py``) is append-only and
        ships no ``remote`` helpers yet; per the contract this lane must not edit
        it, so we issue the request through the client's normalising request seam
        — it still routes every failure through the typed :class:`EngineError`,
        so no raw httpx escapes.
        """
        async with ApplicantEngineClient() as engine:
            try:
                result = await engine._request("POST", path)
            except EngineError as exc:
                raise _engine_http_error(exc) from exc
        return result or {}

    @router.post("/applications/{application_id}/request-final-approval")
    async def request_final_approval(application_id: str, request: Request) -> dict:
        """Ask the engine to (re)notify the user that an application awaits sign-off."""
        _require_user(request)
        return await _remote_action(
            f"/api/remote/applications/{application_id}/request-final-approval"
        )

    @router.post("/applications/{application_id}/resume-account-step")
    async def resume_account_step(application_id: str, request: Request) -> dict:
        """Resume a run parked on the human account-creation step."""
        _require_user(request)
        return await _remote_action(
            f"/api/remote/applications/{application_id}/resume-account-step"
        )

    @router.post("/applications/{application_id}/resume-detection-step")
    async def resume_detection_step(application_id: str, request: Request) -> dict:
        """Resume a run parked on a (now-cleared) detection challenge."""
        _require_user(request)
        return await _remote_action(
            f"/api/remote/applications/{application_id}/resume-detection-step"
        )

    return router
