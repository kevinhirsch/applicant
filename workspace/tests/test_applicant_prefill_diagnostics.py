"""Hermetic tests for the pre-fill diagnostics proxy (dark-engine audit #34).

Mirrors ``test_applicant_admin_routes.py``'s conventions: mounts only
``routes/applicant_admin_routes.py`` on a bare FastAPI app with a tiny
middleware that sets the authenticated user + an ``auth_manager`` stub on app
state, and fakes the engine two ways — a scripted ``FakeEngine`` (happy path +
soft-degrade) and a real ``ApplicantEngineClient`` over an
``httpx.MockTransport`` to prove the exact engine path is hit.

Zero network either way.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.applicant_admin_routes as mod
from routes.applicant_admin_routes import setup_applicant_admin_routes
from src.applicant_engine import ApplicantEngineClient, EngineError


class _AuthMgr:
    def __init__(self, *, configured: bool, admins: set[str] | None = None):
        self.is_configured = configured
        self._admins = admins or set()

    def is_admin(self, user: str) -> bool:
        return user in self._admins


def _make_app(*, user="alice", configured=True, admins=("alice",)) -> FastAPI:
    app = FastAPI()
    app.state.auth_manager = _AuthMgr(configured=configured, admins=set(admins))

    @app.middleware("http")
    async def _auth(request, call_next):
        request.state.current_user = user
        return await call_next(request)

    app.include_router(setup_applicant_admin_routes())
    return app


class FakeEngine:
    calls: list = []
    responses: dict = {}
    raises: dict = {}

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def _maybe(self, key, *args, default=None):
        FakeEngine.calls.append((key, *args))
        if key in FakeEngine.raises:
            raise FakeEngine.raises[key]
        return FakeEngine.responses.get(key, default)

    async def admin_prefill_diagnostics(self):
        return await self._maybe("prefill_diagnostics", default={"diagnostics": []})


@pytest.fixture(autouse=True)
def _reset():
    FakeEngine.calls = []
    FakeEngine.responses = {}
    FakeEngine.raises = {}
    yield


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    return TestClient(_make_app())


# --- auth gating -------------------------------------------------------------


def test_prefill_diagnostics_requires_admin(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    c = TestClient(_make_app(user="bob", configured=True, admins=("alice",)))
    assert c.get("/api/applicant/admin/prefill-diagnostics").status_code == 403


def test_prefill_diagnostics_requires_authentication(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    c = TestClient(_make_app(user=None, configured=True, admins=("alice",)))
    assert c.get("/api/applicant/admin/prefill-diagnostics").status_code == 401


# --- passthrough / soft-degrade ----------------------------------------------


def test_prefill_diagnostics_passthrough_real_messages(client):
    FakeEngine.responses["prefill_diagnostics"] = {
        "diagnostics": [
            "Every credential scope failed for tenant 'workday' (vault unreachable): boom",
            "LLM unavailable during field mapping: rate limited",
        ],
        "status": "live",
    }
    r = client.get("/api/applicant/admin/prefill-diagnostics")
    assert r.status_code == 200
    body = r.json()
    assert body["engine_available"] is True
    assert body["diagnostics"] == [
        "Every credential scope failed for tenant 'workday' (vault unreachable): boom",
        "LLM unavailable during field mapping: rate limited",
    ]
    assert ("prefill_diagnostics",) in FakeEngine.calls


def test_prefill_diagnostics_soft_degrades_when_engine_down(client):
    FakeEngine.raises["prefill_diagnostics"] = EngineError("down", is_timeout=True)
    r = client.get("/api/applicant/admin/prefill-diagnostics")
    assert r.status_code == 200
    body = r.json()
    assert body["engine_available"] is False
    assert body["diagnostics"] == []


# --- exact engine path over a real client + MockTransport --------------------


def test_prefill_diagnostics_hits_exact_engine_path(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        return httpx.Response(200, json={"diagnostics": ["one issue"], "status": "live"})

    class TransportEngine(ApplicantEngineClient):
        def __init__(self, *a, **k):
            super().__init__(base_url="http://api:8000", transport=httpx.MockTransport(handler))

    app = _make_app()
    monkeypatch.setattr(mod, "ApplicantEngineClient", TransportEngine)
    c = TestClient(app)
    r = c.get("/api/applicant/admin/prefill-diagnostics")
    assert r.status_code == 200
    assert seen["path"] == "/api/admin/prefill-diagnostics"
    assert r.json()["diagnostics"] == ["one issue"]
