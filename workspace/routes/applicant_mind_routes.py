# routes/applicant_mind_routes.py
"""Workspace-side proxy for the engine's agent-learning substrate (FR-MIND).

The "What the assistant remembers" + "Saved playbooks" panels and the learning
**curation approvals** are surfaced here. Everything is a thin, auth-protected,
owner-scoped proxy over :class:`src.applicant_engine.ApplicantEngineClient` (the
engine owns the logic; the front door only forwards):

* reads (``GET`` snapshot / skills / curation queue) require a logged-in user;
* writes (approve / deny a curation proposal, **forget a remembered line**) require
  the existing ``can_manage_memory`` privilege, matching the rest of the Brain modal;
* every engine failure surfaces through the typed :class:`EngineError`, translated
  into a clean HTTP response so a wired surface degrades gracefully (a down engine
  reports unavailable rather than 500ing).

The engine routes (``/api/agent-memory/*``) are gated behind the engine's own
LLM-settings gate, so these endpoints only do real work once a model is connected;
until then the section ships grayed via the feature-activation layer.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request

from src.applicant_engine import ApplicantEngineClient, EngineError
from src.auth_helpers import require_privilege, require_user

logger = logging.getLogger(__name__)


def _raise_engine_http(exc: EngineError) -> None:
    """Translate an :class:`EngineError` into an HTTPException for the front-end.

    4xx responses are forwarded (client-correctable). 5xx responses are scrubbed
    — raw detail may contain internal stack traces; logged server-side only.
    """
    if exc.status is None:
        raise HTTPException(503, "The Applicant engine is unavailable right now.") from exc
    if exc.status >= 500:
        logger.warning("engine 5xx (mind): status=%s detail=%s", exc.status, exc.detail or exc.message)
        raise HTTPException(502, "The Applicant engine returned an error.") from exc
    detail = exc.detail if exc.detail is not None else exc.message
    raise HTTPException(exc.status, detail) from exc


async def _engine_get(engine: ApplicantEngineClient, path: str, params: Optional[dict] = None) -> Any:
    return await engine._request("GET", path, params=params)


async def _engine_post(engine: ApplicantEngineClient, path: str, json: Optional[dict] = None) -> Any:
    return await engine._request("POST", path, json=json)


def setup_applicant_mind_routes() -> APIRouter:
    router = APIRouter(prefix="/api/applicant/mind", tags=["applicant-mind"])

    # -- status / activation ------------------------------------------------

    @router.get("/status")
    async def mind_status(request: Request) -> dict:
        """Readiness probe for the memory/playbooks panels.

        Reports whether the engine is reachable and the substrate answers. Never
        raises on a down/unconfigured engine — it just reports ``ready: false`` so
        the panel can show a friendly "not ready yet" note.
        """
        require_user(request)
        async with ApplicantEngineClient() as engine:
            if not await engine.engine_available():
                return {"ready": False, "engine_available": False}
            try:
                await _engine_get(engine, "/api/agent-memory")
            except EngineError:
                return {"ready": False, "engine_available": True}
            return {"ready": True, "engine_available": True}

    # -- what the assistant remembers --------------------------------------

    @router.get("/memory")
    async def memory(request: Request, scope: Optional[str] = None, campaign_id: Optional[str] = None) -> dict:
        """The curated memory the assistant carries (environment + user split)."""
        require_user(request)
        params = {k: v for k, v in {"scope": scope, "campaign_id": campaign_id}.items() if v}
        async with ApplicantEngineClient() as engine:
            try:
                data = await _engine_get(engine, "/api/agent-memory", params or None)
            except EngineError as exc:
                _raise_engine_http(exc)
            return data if isinstance(data, dict) else {"environment": [], "user": [], "truncated": False}

    # -- saved playbooks ----------------------------------------------------

    @router.get("/skills")
    async def skills(request: Request, scope: Optional[str] = None, campaign_id: Optional[str] = None) -> dict:
        """Saved playbooks, metadata only (cheap list)."""
        require_user(request)
        params = {k: v for k, v in {"scope": scope, "campaign_id": campaign_id}.items() if v}
        async with ApplicantEngineClient() as engine:
            try:
                data = await _engine_get(engine, "/api/agent-memory/skills", params or None)
            except EngineError as exc:
                _raise_engine_http(exc)
            return data if isinstance(data, dict) else {"items": []}

    @router.get("/skills/{name}")
    async def skill_detail(request: Request, name: str) -> dict:
        """One saved playbook's full body."""
        require_user(request)
        async with ApplicantEngineClient() as engine:
            try:
                return await _engine_get(engine, f"/api/agent-memory/skills/{name}")
            except EngineError as exc:
                _raise_engine_http(exc)

    # -- forget a remembered line (a WRITE — gated like curation approval) ---

    @router.post("/forget")
    async def forget(request: Request) -> dict:
        """Forget one curated memory line.

        A forget is a write, so it requires the same ``can_manage_memory`` privilege
        as approving a curation proposal; the engine routes it through its own
        review-before-write policy (staged for approval by default, applied only when
        memory approval is relaxed). The body forwards ``ref`` (preferred) or ``text``.
        """
        require_privilege(request, "can_manage_memory")
        try:
            body = await request.json()
        except Exception:
            logger.warning("Bare exception in applicant_mind_routes.py")
            body = {}
        if not isinstance(body, dict):
            body = {}
        payload = {
            k: body.get(k)
            for k in ("ref", "text", "scope", "campaign_id")
            if body.get(k) is not None
        }
        async with ApplicantEngineClient() as engine:
            try:
                return await _engine_post(engine, "/api/agent-memory/forget", json=payload)
            except EngineError as exc:
                _raise_engine_http(exc)

    # -- learning curation approvals (pending review) -----------------------

    @router.get("/curation")
    async def curation(request: Request) -> dict:
        """Proposals the assistant staged for review — approve/deny in the Portal."""
        require_user(request)
        async with ApplicantEngineClient() as engine:
            try:
                data = await _engine_get(engine, "/api/agent-memory/curation")
            except EngineError as exc:
                _raise_engine_http(exc)
            return data if isinstance(data, dict) else {"count": 0, "items": []}

    @router.post("/curation/{proposal_id}/approve")
    async def approve(request: Request, proposal_id: str) -> dict:
        """Approve a staged proposal — apply it to what the assistant remembers."""
        require_privilege(request, "can_manage_memory")
        async with ApplicantEngineClient() as engine:
            try:
                return await _engine_post(engine, f"/api/agent-memory/curation/{proposal_id}/approve")
            except EngineError as exc:
                _raise_engine_http(exc)

    @router.post("/curation/{proposal_id}/deny")
    async def deny(request: Request, proposal_id: str) -> dict:
        """Deny a staged proposal — discard it without applying."""
        require_privilege(request, "can_manage_memory")
        async with ApplicantEngineClient() as engine:
            try:
                return await _engine_post(engine, f"/api/agent-memory/curation/{proposal_id}/deny")
            except EngineError as exc:
                _raise_engine_http(exc)

    return router
