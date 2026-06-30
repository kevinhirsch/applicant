"""MCP server surface — exposes the engine as an MCP server (Issue #308).

Uses fastapi_mcp (MIT) to mount an MCP tool surface on the existing FastAPI
app. Tools are defined as callables that reuse the same guarded application
services — every consequential action passes through the review/stop-boundary
gates.

The MCP surface is mounted optionally: when fastapi_mcp is not installed
(which is the default), the module degrades gracefully with a warning.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, FastAPI, Request

logger = logging.getLogger(__name__)

# Lazy imports — fastapi_mcp is optional
_fastapi_mcp_available = False
try:
    from fastapi_mcp import FastApiMcp
    _fastapi_mcp_available = True
except ImportError:
    _fastapi_mcp_available = False


router = APIRouter(prefix="/mcp", tags=["mcp"])
"""FastAPI router for MCP endpoints.

The actual MCP tool listing (/mcp) is handled by FastApiMcp mounting.
This router serves as a namespace marker.
"""

#: The read-only MCP tools the native surface advertises. Consequential actions
#: (final submit) are deliberately NOT exposed here — they remain behind the
#: human review / stop-boundary gates, exactly like the HTTP surface (#308).
_NATIVE_TOOL_SPECS: list[dict] = [
    {"name": "list_campaigns", "description": "List all campaigns."},
    {"name": "get_attributes", "description": "List the attribute cloud (stored applicant facts)."},
    {"name": "get_applications", "description": "List all applications and their states."},
    {"name": "get_pending_actions", "description": "List open pending actions needing human attention."},
    {"name": "health", "description": "Check the engine's health status."},
]


def _container_storage(app_state) -> Any:
    container = getattr(app_state, "container", None)
    if container is None:
        return None
    return getattr(container, "storage", None)


@router.get("/tools")
@router.post("/tools/list")
async def mcp_tools_list() -> dict:
    """Advertise the engine's capabilities as MCP tools (#308).

    Always mounted (no optional dependency) so an MCP client can discover the
    engine's tool surface. Mirrors the ``tools/list`` JSON-RPC result shape.
    """
    return {
        "tools": [
            {
                "name": t["name"],
                "description": t["description"],
                "inputSchema": {"type": "object", "properties": {}},
            }
            for t in _NATIVE_TOOL_SPECS
        ]
    }


@router.post("/tools/call")
async def mcp_tools_call(request: Request, payload: dict) -> dict:
    """Invoke an MCP tool, reusing the same guarded application services (#308).

    Only read-only tools are callable here; a request for a consequential action
    is refused — the final submit stays behind the human review / stop-boundary
    gate, never auto-authorized via MCP (the same boundary as the HTTP surface).
    """
    name = str(payload.get("name") or payload.get("tool") or "")
    storage = _container_storage(request.app.state)

    handlers = {
        "list_campaigns": lambda: _tool_list_campaigns(storage) if storage else [],
        "get_attributes": lambda: _tool_get_attributes(storage) if storage else [],
        "get_applications": lambda: _tool_get_applications(storage) if storage else [],
        "get_pending_actions": lambda: _tool_get_pending_actions(storage) if storage else [],
        "health": lambda: _tool_health_check(request.app.state),
    }
    handler = handlers.get(name)
    if handler is None:
        # Default-deny: an unknown / consequential tool is not silently executed.
        return {
            "isError": True,
            "content": [
                {
                    "type": "text",
                    "text": (
                        f"Tool '{name}' is not available over MCP. Consequential "
                        "actions stay behind human review and cannot be invoked here."
                    ),
                }
            ],
        }
    return {"isError": False, "result": handler()}


def _tool_list_campaigns(storage) -> list[dict]:
    """List all campaigns in the system.

    Returns basic campaign metadata (id, name, status, job_title).
    """
    campaigns = storage.campaigns.list()
    return [
        {
            "id": str(c.id),
            "name": c.name,
            "status": c.status.value if hasattr(c.status, "value") else str(c.status),
            "job_title": c.job_title,
        }
        for c in campaigns
    ]


def _tool_get_attributes(storage) -> list[dict]:
    """List all stored attributes (the attribute cloud).

    Returns every stored fact about the applicant (name, email, skills, etc.).
    """
    attrs = storage.attributes.list()
    return [
        {"id": str(a.id), "name": a.name, "value": a.value, "category": a.category}
        for a in attrs
    ]


def _tool_get_applications(storage) -> list[dict]:
    """List all applications and their current state."""
    apps = storage.applications.list()
    return [
        {"id": str(a.id), "campaign_id": str(a.campaign_id),
         "status": a.status.value if hasattr(a.status, "value") else str(a.status),
         "url": a.url if hasattr(a, "url") else ""}
        for a in apps
    ]


def _tool_get_pending_actions(storage) -> list[dict]:
    """List all open pending actions that need human attention."""
    actions = []
    try:
        for pa in storage.pending_actions.list_open():
            actions.append({
                "id": str(pa.id),
                "kind": pa.kind,
                "title": pa.title,
                "campaign_id": str(pa.campaign_id),
                "application_id": str(pa.application_id) if pa.application_id else None,
                "payload": dict(pa.payload) if pa.payload else {},
            })
    except Exception:
        logger.warning("Failed to list pending actions")
    return actions


def _tool_health_check(app_state) -> dict:
    """Check the engine's health."""
    container = getattr(app_state, "container", None)
    if container is None:
        return {"status": "no_container", "healthy": False}
    return {
        "status": "ok",
        "healthy": True,
        "version": "0.1.0",
        "storage_type": type(getattr(container, "storage", None)).__name__,
        "llm_configured": getattr(container, "llm", None) is not None,
    }


def mount_mcp(app: FastAPI) -> None:
    """Mount the MCP server surface on the FastAPI app (#308).

    The native ``/mcp/tools`` + ``/mcp/tools/call`` JSON surface is ALWAYS
    mounted (no optional dependency) so the engine advertises its capabilities
    as MCP tools out of the box. When ``fastapi_mcp`` is also installed it
    additionally mounts the SSE transport for streaming MCP clients.
    """
    # Always mount the dependency-free native MCP tool surface. Register the
    # routes directly on the app (not via include_router) so they appear as flat
    # APIRoutes with a ``/mcp`` path — discoverable by clients and reachability
    # checks alike.
    if not any("/mcp/tools" in getattr(r, "path", "") for r in app.routes):
        app.add_api_route("/mcp/tools", mcp_tools_list, methods=["GET"], tags=["mcp"])
        app.add_api_route("/mcp/tools/list", mcp_tools_list, methods=["POST"], tags=["mcp"])
        app.add_api_route("/mcp/tools/call", mcp_tools_call, methods=["POST"], tags=["mcp"])
        logger.info("Native MCP tool surface mounted at /mcp/tools")

    if not _fastapi_mcp_available:
        logger.info(
            "fastapi_mcp not installed — the streaming MCP (SSE) transport is "
            "unavailable; the native /mcp/tools surface is mounted. Install with "
            "'uv sync --extra mcp' to enable streaming."
        )
        return

    try:
        mcp_server = FastApiMcp(
            app,
            mount_path="/mcp",
            name="Applicant Engine",
            description="Autonomous job-application agent — MCP interface for "
                        "external agents to discover and invoke guarded "
                        "application services.",
        )

        @mcp_server.tool()
        async def list_campaigns() -> list[dict]:
            """List all campaigns."""
            container = getattr(app.state, "container", None)
            if container is None:
                return []
            storage = getattr(container, "storage", None)
            if storage is None:
                return []
            return _tool_list_campaigns(storage)

        @mcp_server.tool()
        async def get_attributes() -> list[dict]:
            """List the attribute cloud (stored applicant facts)."""
            container = getattr(app.state, "container", None)
            if container is None:
                return []
            storage = getattr(container, "storage", None)
            if storage is None:
                return []
            return _tool_get_attributes(storage)

        @mcp_server.tool()
        async def get_applications() -> list[dict]:
            """List all applications and their states."""
            container = getattr(app.state, "container", None)
            if container is None:
                return []
            storage = getattr(container, "storage", None)
            if storage is None:
                return []
            return _tool_get_applications(storage)

        @mcp_server.tool()
        async def get_pending_actions() -> list[dict]:
            """List all open pending actions."""
            container = getattr(app.state, "container", None)
            if container is None:
                return []
            storage = getattr(container, "storage", None)
            if storage is None:
                return []
            return _tool_get_pending_actions(storage)

        @mcp_server.tool()
        async def health() -> dict:
            """Check the engine's health status."""
            return _tool_health_check(app.state)

        logger.info("MCP server surface mounted at /mcp")

    except Exception as exc:
        logger.warning("Failed to mount MCP surface: %s", exc)


def wire_mcp_tools(container) -> list[dict[str, Any]]:
    """Return MCP tool descriptors for external use.

    Used by tests and external integrations.
    """
    storage = getattr(container, "storage", None)
    tools = []

    if storage is not None:
        tools.append({
            "name": "list_campaigns",
            "description": "List all campaigns",
            "handler": lambda s=storage: _tool_list_campaigns(s),
        })
        tools.append({
            "name": "get_attributes",
            "description": "List the attribute cloud",
            "handler": lambda s=storage: _tool_get_attributes(s),
        })
        tools.append({
            "name": "get_applications",
            "description": "List all applications and their states",
            "handler": lambda s=storage: _tool_get_applications(s),
        })
        tools.append({
            "name": "get_pending_actions",
            "description": "List all open pending actions",
            "handler": lambda s=storage: _tool_get_pending_actions(s),
        })

    tools.append({
        "name": "health",
        "description": "Check the engine's health status",
        "handler": lambda c=container: _tool_health_check(
            type("state", (), {"container": c})
        ),
    })

    return tools
