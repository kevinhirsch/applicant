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

Note: the user-driven, non-destructive remote actions (request a final-approval
ping; resume a run parked on a human account-creation step or a cleared
detection challenge) are NOT duplicated here — they are owned end-to-end by
``applicant_remote_routes.py`` / ``applicantRemote.js``. This file used to carry
its own copies of those three routes, but nothing on the chat surface ever
called them (dark-engine audit item 3, §B1); they were removed rather than left
as a second, unused path to the same engine actions.

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
import re

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


class ConfirmCriteriaIn(BaseModel):
    """Commit a confirmation-gated criteria refocus (FR-FB-3 / FR-CRIT)."""
    campaign_id: str
    changes: dict


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

#: User-facing fields of a control action (the agent-loop steering result for a
#: turn). The in-chat criteria-confirm affordance (``applicantChat.js``) reads
#: ``kind`` / ``requires_confirmation`` / ``applied`` to decide whether to render
#: the Confirm button, and ``detail`` for the change summary + the
#: ``/confirm-criteria`` body. ``ok`` keeps the reply truthful about an action the
#: agent could not take. Anything else the engine might attach is dropped.
_SAFE_CONTROL_KEYS = frozenset({"kind", "applied", "requires_confirmation", "ok"})


def _scrub_chat_reply(raw: dict) -> dict:
    """Whitelist the engine's chat reply to only user-facing fields.

    Forwards ``message`` / ``gaps`` / ``proposed_changes`` and the turn's
    ``control_actions`` (validated/shaped like the siblings) so the in-chat
    criteria-refocus confirm affordance renders. Any other field the engine
    attaches is not forwarded to the browser.
    """
    changes = []
    for c in raw.get("proposed_changes") or []:
        if isinstance(c, dict):
            changes.append({k: v for k, v in c.items() if k in _SAFE_CHANGE_KEYS})
    controls = []
    for a in raw.get("control_actions") or []:
        if not isinstance(a, dict):
            continue
        shaped = {k: v for k, v in a.items() if k in _SAFE_CONTROL_KEYS}
        # ``detail`` is the criteria summary + the /confirm-criteria body; keep it
        # as a shallow dict (drop any nested non-primitive the engine may attach).
        detail = a.get("detail")
        shaped["detail"] = (
            {
                k: v
                for k, v in detail.items()
                if isinstance(v, (str, int, float, bool, type(None)))
            }
            if isinstance(detail, dict)
            else {}
        )
        controls.append(shaped)
    return {
        "message": raw.get("message") or "",
        "gaps": [g for g in (raw.get("gaps") or []) if isinstance(g, str)],
        "proposed_changes": changes,
        "control_actions": controls,
    }


#: Matches a canonical UUID (the engine's internal campaign/application/run ids).
_UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)

#: Engine reply keys that carry internal identifiers and must never reach the
#: browser. The surface addresses campaigns/applications by the user-chosen name,
#: not the engine's internal UUID, so these are dropped wholesale.
_INTERNAL_ID_KEYS = frozenset(
    {"campaign_id", "application_id", "run_id", "workflow_id", "task_id"}
)


def scrub_engine_reply(reply: dict) -> dict:
    """Strip internal identifiers from an engine chat reply before forwarding (#317).

    The engine attaches internal UUIDs (campaign/application/run ids) both as
    top-level keys and, occasionally, inline inside human-readable text. Forwarding
    them verbatim leaks engine-internal state to the browser. This scrubber:

    * drops the internal-id keys (``campaign_id`` etc.) from the payload, and
    * redacts any UUID embedded in string values (recursively) to ``[id]``,

    so no internal identifier survives in the serialized reply. It is shape-
    preserving for everything else and never raises.
    """

    def _scrub(value):
        if isinstance(value, str):
            return _UUID_RE.sub("[id]", value)
        if isinstance(value, dict):
            return {
                k: _scrub(v)
                for k, v in value.items()
                if k not in _INTERNAL_ID_KEYS
            }
        if isinstance(value, list):
            return [_scrub(v) for v in value]
        return value

    if not isinstance(reply, dict):
        return reply
    return _scrub(reply)


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
        # #232: the panel JS iterates ``campaigns`` directly, so a non-list engine
        # response (e.g. a dict-shaped error/envelope) would crash the front-end
        # iteration. Coerce anything that is not a bare list to an empty list — the
        # panel then renders its empty state instead of throwing.
        if not isinstance(campaigns, list):
            campaigns = []
        return {"engine_available": True, "campaigns": campaigns}

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
        # Whitelist user-facing fields, then strip any internal identifiers
        # (campaign UUID etc.) that survive in free-text before forwarding (#317).
        return scrub_engine_reply(_scrub_chat_reply(result or {}))

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

    @router.post("/confirm-criteria")
    async def confirm_criteria(body: ConfirmCriteriaIn, request: Request) -> dict:
        """Commit a confirmation-gated criteria refocus the user approved
        (FR-FB-3, FR-CRIT)."""
        _require_user(request)
        async with ApplicantEngineClient() as engine:
            try:
                result = await engine.chat_confirm_criteria(
                    {
                        "campaign_id": body.campaign_id,
                        "changes": body.changes,
                    }
                )
            except EngineError as exc:
                raise _engine_http_error(exc) from exc
        return result or {}

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

    # Dark-engine audit item 3: this lane used to carry its own
    # request-final-approval / resume-account-step / resume-detection-step
    # proxies (a `_remote_action` helper posting straight to
    # `/api/remote/applications/{id}/...`), but `applicantChat.js` never called
    # any of them -- the remote lane (`applicant_remote_routes.py` ->
    # `applicantRemote.js`) already owns these exact actions end-to-end. Removed
    # rather than left as an unused second path to the same engine endpoints.

    return router
