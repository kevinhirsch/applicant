# routes/applicant_capabilities_routes.py
"""Assistant capability disclosure ↔ engine bridge (dark-engine audit item 24:
"MCP tool surface is entirely undocumented product capability").

The engine exposes a native, dependency-free MCP tool surface
(``src/applicant/app/routers/mcp.py``, ``GET /mcp/tools`` /
``POST /mcp/tools/list``) advertising the read-only tools the agent (and any
external MCP client) can call — but the owner never saw what the assistant can
actually do. This proxy SURFACES that same list in the front door. It adds no
engine logic and creates no new engine state: a thin, auth-protected,
owner-scoped proxy over :class:`src.applicant_engine.ApplicantEngineClient`
(the browser never reaches the engine directly), modelled on the sibling
``applicant_activity_routes.py`` / ``applicant_results_routes.py``.

Never fabricates tools: the response renders ONLY what the engine's
``/mcp/tools`` list actually returns (today: ``list_campaigns``,
``get_attributes``, ``get_applications``, ``get_pending_actions``, ``health``
— all read-only; consequential actions such as final-submit are deliberately
absent from the engine's own list and so can never appear here). If the
engine's tool surface changes, this proxy's output changes with it — nothing
here is hardcoded.

Degrades soft, exactly like the sibling proxies:

* an unreachable engine → ``engine_available: false`` with a well-formed empty
  ``tools: []``;
* a setup/permission gate (the engine gates ``/mcp/tools`` behind
  ``require_llm_configured`` — 409 until an AI model is connected) →
  ``gated: true`` with the engine's own plain-language message, forwarded
  honestly (never silently emptied to "no capabilities").

Endpoint (one route, no campaign scoping — the engine's tool list is global,
not per-campaign):

* ``GET /api/applicant/capabilities`` — the plain-language "what the assistant
  can do" list: ``[{"name", "description"}, ...]``.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request

from src.applicant_engine import (
    ApplicantEngineClient,
    EngineError,
    shared_engine_http_client,
    soft_degrade,
)
from src.auth_helpers import require_user

logger = logging.getLogger(__name__)


def _require_user(request: Request) -> str:
    """Require an authenticated owner (the global gate also enforces this)."""
    return require_user(request)


def _clean_tools(raw: object) -> list[dict]:
    """Normalise the engine's raw ``tools`` list to ``{"name", "description"}``
    dicts, dropping anything malformed. Never invents a name/description that
    the engine didn't actually advertise."""
    tools = raw if isinstance(raw, list) else []
    out: list[dict] = []
    for t in tools:
        if not isinstance(t, dict):
            continue
        name = str(t.get("name") or "").strip()
        if not name:
            continue
        out.append({"name": name, "description": str(t.get("description") or "").strip()})
    return out


def setup_applicant_capabilities_routes() -> APIRouter:
    router = APIRouter(prefix="/api/applicant/capabilities", tags=["applicant-capabilities"])

    @router.get("")
    async def capabilities(request: Request) -> dict:
        """The assistant's plain-language "what can it do" list.

        Proxies the engine's native MCP tool surface (``GET /mcp/tools``) — the
        SAME list the engine advertises to external MCP clients — as a
        read-only, owner-facing disclosure. Degrades soft: an unreachable
        engine returns ``engine_available: false``; the engine's own
        LLM-configured gate returns ``gated: true`` with its message, rather
        than a bare empty list that would read as "the assistant can do
        nothing".
        """
        _require_user(request)
        empty = {"tools": [], "count": 0}
        async with ApplicantEngineClient(client=shared_engine_http_client(request)) as engine:
            try:
                data = await engine.mcp_tools_list()
            except EngineError as exc:
                logger.debug("capabilities: mcp tools read failed (status=%s): %s", exc.status, exc)
                return soft_degrade(exc, empty)

        tools = _clean_tools(data.get("tools") if isinstance(data, dict) else None)
        return {
            "engine_available": True,
            "tools": tools,
            "count": len(tools),
        }

    return router
