"""Hermetic tests for the "what the assistant can do" capability proxy
(dark-engine audit item 24).

Mounts only ``routes/applicant_capabilities_routes.py`` on a bare FastAPI app
with a tiny middleware that authenticates the request (the real global auth
gate lives in ``app.py`` and is out of scope here). The engine is faked two
ways:

* a scripted ``FakeEngine`` patched in for ``ApplicantEngineClient`` (covers
  the proxied shape and the soft-degrade / gate paths), and
* a real :class:`ApplicantEngineClient` over an ``httpx.MockTransport``
  proving the exact engine path (``GET /mcp/tools``) is hit.

Zero network either way. Mirrors ``test_applicant_results_routes.py``.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.applicant_capabilities_routes as mod
from routes.applicant_capabilities_routes import setup_applicant_capabilities_routes
from src.applicant_engine import ApplicantEngineClient, EngineError


# --- test app with a stand-in auth middleware -------------------------------


def _make_app(authed: bool = True) -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def _auth(request, call_next):
        request.state.current_user = "tester" if authed else None
        return await call_next(request)

    app.include_router(setup_applicant_capabilities_routes())
    return app


# --- a scripted fake engine -------------------------------------------------


class FakeEngine:
    """Stands in for ApplicantEngineClient as an async context manager."""

    calls: list = []
    tools_response: dict = {}
    raises: dict = {}

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def mcp_tools_list(self):
        FakeEngine.calls.append("mcp_tools_list")
        if "mcp_tools_list" in FakeEngine.raises:
            raise FakeEngine.raises["mcp_tools_list"]
        return FakeEngine.tools_response


@pytest.fixture(autouse=True)
def _reset_fake():
    FakeEngine.calls = []
    FakeEngine.tools_response = {}
    FakeEngine.raises = {}
    yield


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    return TestClient(_make_app())


_REAL_TOOLS = [
    {"name": "list_campaigns", "description": "List all campaigns.", "inputSchema": {}},
    {"name": "get_attributes", "description": "List the attribute cloud (stored applicant facts).", "inputSchema": {}},
    {"name": "get_applications", "description": "List all applications and their states.", "inputSchema": {}},
    {"name": "get_pending_actions", "description": "List open pending actions needing human attention.", "inputSchema": {}},
    {"name": "health", "description": "Check the engine's health status.", "inputSchema": {}},
]


# --- auth --------------------------------------------------------------------


def test_unauthenticated_is_rejected(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    c = TestClient(_make_app(authed=False))
    r = c.get("/api/applicant/capabilities")
    assert r.status_code == 401


# --- happy path: proxies the engine's REAL tool list, never fabricates -----


def test_proxies_the_engines_real_tool_list(client):
    FakeEngine.tools_response = {"tools": _REAL_TOOLS}
    r = client.get("/api/applicant/capabilities")
    assert r.status_code == 200
    body = r.json()
    assert body["engine_available"] is True
    assert body["count"] == 5
    names = {t["name"] for t in body["tools"]}
    assert names == {
        "list_campaigns", "get_attributes", "get_applications",
        "get_pending_actions", "health",
    }
    # Descriptions pass straight through — no fabrication, no rewriting.
    by_name = {t["name"]: t["description"] for t in body["tools"]}
    assert by_name["list_campaigns"] == "List all campaigns."
    assert by_name["health"] == "Check the engine's health status."
    assert ("mcp_tools_list") in FakeEngine.calls


def test_never_invents_a_tool_beyond_what_the_engine_advertises(client):
    """If the engine's list shrinks (e.g. a future hardening pass removes a
    tool), this proxy must reflect that — never padding in a stale/fabricated
    entry."""
    FakeEngine.tools_response = {"tools": [_REAL_TOOLS[0]]}
    r = client.get("/api/applicant/capabilities")
    body = r.json()
    assert body["count"] == 1
    assert body["tools"] == [{"name": "list_campaigns", "description": "List all campaigns."}]


def test_consequential_actions_are_never_present():
    """Sanity: the engine's own list never includes a write/submit tool, so
    this proxy — which only ever forwards what the engine returns — can never
    surface one either. Locks the assumption the front-door copy relies on."""
    names = {t["name"] for t in _REAL_TOOLS}
    for forbidden in ("submit", "final_submit", "authorize_engine_finish", "apply"):
        assert forbidden not in names


# --- malformed / empty engine payloads degrade to a well-formed empty list --


def test_malformed_tool_entries_are_dropped_not_fabricated(client):
    FakeEngine.tools_response = {
        "tools": [
            {"name": "health", "description": "Check the engine's health status."},
            {"description": "missing a name — dropped"},
            "not-even-a-dict",
            None,
        ]
    }
    r = client.get("/api/applicant/capabilities")
    body = r.json()
    assert body["count"] == 1
    assert body["tools"] == [{"name": "health", "description": "Check the engine's health status."}]


def test_empty_tools_list_is_a_well_formed_empty_state(client):
    FakeEngine.tools_response = {"tools": []}
    r = client.get("/api/applicant/capabilities")
    body = r.json()
    assert body["engine_available"] is True
    assert body["tools"] == []
    assert body["count"] == 0


def test_non_dict_response_degrades_to_empty(client):
    FakeEngine.tools_response = None
    r = client.get("/api/applicant/capabilities")
    body = r.json()
    assert body["engine_available"] is True
    assert body["tools"] == []


# --- soft-degrade: transport offline -----------------------------------------


def test_soft_degrades_when_engine_unreachable(client):
    FakeEngine.raises["mcp_tools_list"] = EngineError("down", is_timeout=True)
    r = client.get("/api/applicant/capabilities")
    assert r.status_code == 200
    body = r.json()
    assert body["engine_available"] is False
    assert body.get("gated") is not True
    assert body["tools"] == []


# --- HONESTY: a setup gate is NOT offline ------------------------------------
#
# The engine gates /mcp/tools behind require_llm_configured (409 until an AI
# model is connected). That must surface as GATED (gated:true + the engine's
# message, engine_available:true), never as a bare "the assistant has no
# capabilities" empty list.

_GATE_MSG = "Connect an AI model first to continue. You can do this in the setup wizard or under Settings."


def test_409_gate_is_not_offline_and_forwards_the_engines_message(client):
    FakeEngine.raises["mcp_tools_list"] = EngineError("gated", status=409, detail=_GATE_MSG)
    r = client.get("/api/applicant/capabilities")
    assert r.status_code == 200
    body = r.json()
    assert body["gated"] is True
    assert body["engine_available"] is True
    assert body["message"] == _GATE_MSG
    assert body["tools"] == []


# --- exact engine path via a real client over MockTransport ------------------


def _mock_transport_app(handler):
    class TransportEngine(ApplicantEngineClient):
        def __init__(self, *a, **k):
            super().__init__(base_url="http://api:8000", transport=httpx.MockTransport(handler))

    app = FastAPI()

    @app.middleware("http")
    async def _auth(request, call_next):
        request.state.current_user = "tester"
        return await call_next(request)

    app.include_router(setup_applicant_capabilities_routes())
    return app, TransportEngine


def test_hits_the_exact_engine_mcp_tools_path(monkeypatch):
    paths = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append((request.method, request.url.path))
        if request.url.path == "/mcp/tools":
            return httpx.Response(200, json={"tools": _REAL_TOOLS})
        return httpx.Response(404, json={"detail": "unexpected"})

    app, engine_cls = _mock_transport_app(handler)
    monkeypatch.setattr(mod, "ApplicantEngineClient", engine_cls)
    c = TestClient(app)

    r = c.get("/api/applicant/capabilities")
    assert r.status_code == 200
    assert ("GET", "/mcp/tools") in paths
    body = r.json()
    assert body["count"] == 5


def test_409_over_mock_transport_surfaces_as_gated(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/mcp/tools":
            return httpx.Response(409, json={"detail": _GATE_MSG})
        return httpx.Response(404, json={"detail": "unexpected"})

    app, engine_cls = _mock_transport_app(handler)
    monkeypatch.setattr(mod, "ApplicantEngineClient", engine_cls)
    c = TestClient(app)

    r = c.get("/api/applicant/capabilities")
    assert r.status_code == 200
    body = r.json()
    assert body["gated"] is True
    assert body["message"] == _GATE_MSG
