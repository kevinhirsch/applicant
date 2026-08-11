"""#828 (AZ0-6 seam gate) — the a0 shell pre-registers the Applicant engine's MCP surface.

Hermetic contract test (no network, parallel-safe): parses ``docker/docker-compose.prod.yml``
and asserts the ``a0`` service seeds ``A0_SET_MCP_SERVERS`` so a fresh install registers the
engine's MCP tools automatically. A0 reads this as the ``mcp_servers`` settings default via
``get_default_value("mcp_servers", ...)`` -> ``A0_SET_MCP_SERVERS`` (``helpers/settings.py`` +
``helpers/dotenv.py`` ``os.getenv``). The engine mounts SSE at ``/mcp``
(``src/applicant/app/mcp_server.py``); A0's MCP client supports the ``sse`` transport
(``helpers/mcp_handler.py``).

This pins the BUILDABLE half of #828. The LIVE seam-proof — tools discovered through the
seam, campaigns/pending listed, and a consequential submit refused server-side — is the
separate go/no-go against a booted compose stack (recorded on PR #822).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

COMPOSE = Path(__file__).resolve().parents[2] / "docker" / "docker-compose.prod.yml"


def _a0_environment() -> dict:
    data = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    a0 = data["services"]["a0"]
    env = a0.get("environment", {})
    # compose allows list- or map-form environment; normalise to a dict
    if isinstance(env, list):
        out = {}
        for item in env:
            k, _, v = str(item).partition("=")
            out[k] = v
        return out
    return dict(env)


def _resolve_compose_vars(raw: str) -> str:
    # substitute ${VAR:-default} with its default so the JSON is loadable offline
    return re.sub(r"\$\{[A-Z_]+:-([^}]*)\}", r"\1", raw)


def test_a0_service_seeds_mcp_servers_default():
    env = _a0_environment()
    assert "A0_SET_MCP_SERVERS" in env, (
        "the a0 service must seed the mcp_servers settings default via A0_SET_MCP_SERVERS "
        "so the engine is pre-registered out of the box"
    )


def test_engine_registered_as_sse_mcp_server_at_mcp_endpoint():
    env = _a0_environment()
    cfg = json.loads(_resolve_compose_vars(env["A0_SET_MCP_SERVERS"]))
    servers = cfg.get("mcpServers", {})
    assert "applicant-engine" in servers, "the engine must be pre-registered as 'applicant-engine'"
    engine = servers["applicant-engine"]
    assert engine["url"].endswith("/mcp"), f"engine MCP url must target /mcp, got {engine['url']!r}"
    assert engine["type"] == "sse", "engine transport must be 'sse' (engine mounts fastapi_mcp SSE at /mcp)"
    assert engine.get("disabled") is False, "the engine registration must be enabled by default"


def test_engine_mcp_url_points_at_the_internal_engine_service():
    # the raw value should reference the engine's in-network address (ENGINE_URL / api:8000)
    raw = _a0_environment()["A0_SET_MCP_SERVERS"]
    assert "/mcp" in raw
    assert ("ENGINE_URL" in raw) or ("api:8000" in raw), (
        "the engine MCP url must resolve to the in-network engine service (ENGINE_URL / http://api:8000)"
    )
