"""MCP server endpoint — exposes the engine as an MCP server via fastapi_mcp.

Uses ``fastapi_mcp.FastApiMCP`` to add an SSE endpoint to the FastAPI app,
registering engine capabilities as MCP tools that MCP clients (Claude Desktop,
VS Code, etc.) can discover and invoke.

Reference tools adopted:
- **Agent status** — query current agent state, pending actions, run history.
- **Memory query** — read curated agent memory/skills (advisory).
- **Discovery sources** — list configured discovery sources.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI

log = logging.getLogger(__name__)


def register_mcp_server(app: FastAPI) -> None:
    """Mount the MCP server endpoint on ``app``.

    Adds an ``/mcp`` SSE endpoint that exposes registered tools. The server
    reads engine state from ``app.state.container``.
    """
    try:
        from fastapi_mcp import FastApiMCP
    except ImportError as exc:
        log.warning("fastapi_mcp not installed — MCP server disabled (%s)", exc)
        return

    try:
        mcp_server = FastApiMCP(
            app,
            name="Applicant Engine",
            description="Autonomous job-application agent — MCP interface",
        )
        mcp_server.mount_sse(app, mount_path="/mcp")
        log.info("MCP server mounted at /mcp (SSE)")
    except Exception as exc:
        log.warning("Failed to mount MCP server: %s", exc)
