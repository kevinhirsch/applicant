"""Hermetic tests for the honest health panel proxy (P1-3, issue #655).

Mounts only ``routes/applicant_health_routes.py`` on a bare FastAPI app. The
engine is faked with a scripted double (mirrors
``test_applicant_capabilities_routes.py`` / ``test_applicant_results_routes.py``).
Owner-gating coverage mirrors ``test_applicant_crossuser_isolation_disc15.py``'s
``_AuthMgr`` + middleware convention. Zero network.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.applicant_health_routes as mod
from routes.applicant_health_routes import setup_applicant_health_routes
from src.applicant_engine import EngineError


class _AuthMgr:
    """Minimal stand-in for the real ``AuthManager``."""

    def __init__(self, *, configured: bool, admins: set[str] | None = None):
        self.is_configured = configured
        self._admins = set(admins or ())

    def is_admin(self, user: str) -> bool:
        return user in self._admins


def _mount(*, user, configured: bool, admins=("owner",)) -> FastAPI:
    app = FastAPI()
    app.state.auth_manager = _AuthMgr(configured=configured, admins=admins)

    @app.middleware("http")
    async def _auth(request, call_next):
        request.state.current_user = user
        return await call_next(request)

    app.include_router(setup_applicant_health_routes())
    return app


class FakeEngine:
    """Stands in for ApplicantEngineClient as an async context manager."""

    calls: list = []
    response: dict = {}
    raises: dict = {}

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def health_capabilities(self):
        FakeEngine.calls.append("health_capabilities")
        if "health_capabilities" in FakeEngine.raises:
            raise FakeEngine.raises["health_capabilities"]
        return FakeEngine.response


@pytest.fixture(autouse=True)
def _reset_fake():
    FakeEngine.calls = []
    FakeEngine.response = {}
    FakeEngine.raises = {}
    yield


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    return TestClient(_mount(user="owner", configured=False))


_ALL_REAL = {
    "generated_at": "2026-07-08T00:00:00+00:00",
    "version": "0.1.0",
    "capabilities": [
        {"name": "postgres", "label": "Database (Postgres)", "status": "real",
         "detail": "ok (connected)", "load_bearing": True, "fix": ""},
        {"name": "resume_renderer", "label": "Résumé renderer", "status": "real",
         "detail": "backed by lualatex", "load_bearing": True, "fix": ""},
        {"name": "browser", "label": "Automation browser", "status": "real",
         "detail": "ok (camoufox)", "load_bearing": True, "fix": ""},
        {"name": "orchestrator", "label": "Durable orchestrator", "status": "real",
         "detail": "in-process checkpoint shim", "load_bearing": False, "fix": ""},
    ],
    "degraded": [],
    "load_bearing_degraded": [],
    "all_real": True,
}

_ONE_DEGRADED = {
    "generated_at": "2026-07-08T00:00:00+00:00",
    "capabilities": [
        {"name": "postgres", "label": "Database (Postgres)", "status": "stub",
         "detail": "NOT REACHABLE (using in-memory storage)", "load_bearing": True,
         "fix": "Set DATABASE_URL to a reachable Postgres instance..."},
        {"name": "resume_renderer", "label": "Résumé renderer", "status": "real",
         "detail": "backed by lualatex", "load_bearing": True, "fix": ""},
        {"name": "browser", "label": "Automation browser", "status": "real",
         "detail": "ok (camoufox)", "load_bearing": True, "fix": ""},
        {"name": "orchestrator", "label": "Durable orchestrator", "status": "real",
         "detail": "in-process checkpoint shim", "load_bearing": False, "fix": ""},
    ],
    "degraded": ["postgres"],
    "load_bearing_degraded": ["postgres"],
    "all_real": False,
}


# --- happy path: all real -----------------------------------------------------


def test_proxies_the_engines_real_report_verbatim(client):
    FakeEngine.response = _ALL_REAL
    r = client.get("/api/applicant/health/capabilities")
    assert r.status_code == 200
    body = r.json()
    assert body["engine_available"] is True
    assert body["all_real"] is True
    assert body["degraded"] == []
    assert len(body["capabilities"]) == 4
    names = {c["name"] for c in body["capabilities"]}
    assert names == {"postgres", "resume_renderer", "browser", "orchestrator"}
    assert ("health_capabilities") in FakeEngine.calls
    # P3-5 (release engineering): the engine's real version is proxied verbatim.
    assert body["version"] == "0.1.0"


def test_missing_version_from_engine_proxies_as_empty_not_invented(client):
    FakeEngine.response = _ONE_DEGRADED  # has no "version" key
    r = client.get("/api/applicant/health/capabilities")
    body = r.json()
    assert body["version"] == ""


def test_degraded_item_carries_fix_copy_and_load_bearing_flag(client):
    FakeEngine.response = _ONE_DEGRADED
    r = client.get("/api/applicant/health/capabilities")
    body = r.json()
    assert body["all_real"] is False
    assert body["degraded"] == ["postgres"]
    assert body["load_bearing_degraded"] == ["postgres"]
    postgres = next(c for c in body["capabilities"] if c["name"] == "postgres")
    assert postgres["status"] == "stub"
    assert postgres["load_bearing"] is True
    assert postgres["fix"], "a degraded item must carry actionable fix copy, not a bare dot"


# --- malformed / empty engine payloads degrade to a well-formed empty state --


def test_malformed_capability_entries_are_dropped_not_fabricated(client):
    FakeEngine.response = {
        "generated_at": "x",
        "capabilities": [
            {"name": "postgres", "status": "real"},
            {"status": "real"},  # missing name -> dropped
            "not-even-a-dict",
            None,
        ],
        "degraded": [],
        "load_bearing_degraded": [],
        "all_real": True,
    }
    r = client.get("/api/applicant/health/capabilities")
    body = r.json()
    assert len(body["capabilities"]) == 1
    assert body["capabilities"][0]["name"] == "postgres"


def test_non_dict_response_degrades_to_empty(client):
    FakeEngine.response = None
    r = client.get("/api/applicant/health/capabilities")
    body = r.json()
    assert body["engine_available"] is True
    assert body["capabilities"] == []
    assert body["all_real"] is True


# --- soft-degrade: transport offline (single designed banner, not blank) -----


def test_soft_degrades_when_engine_unreachable(client):
    FakeEngine.raises["health_capabilities"] = EngineError("down", is_timeout=True)
    r = client.get("/api/applicant/health/capabilities")
    assert r.status_code == 200
    body = r.json()
    assert body["engine_available"] is False
    assert body["capabilities"] == []
    assert body.get("gated") is not True


def test_gate_is_not_offline_and_forwards_the_engines_message(client):
    msg = "Setup is required before this is available."
    FakeEngine.raises["health_capabilities"] = EngineError("gated", status=409, detail=msg)
    r = client.get("/api/applicant/health/capabilities")
    body = r.json()
    assert body["gated"] is True
    assert body["engine_available"] is True
    assert body["message"] == msg


# --- owner-gating (DISC-15 class) --------------------------------------------


def test_unauthenticated_unconfigured_non_loopback_denied(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    app = _mount(user=None, configured=False)
    c = TestClient(app)
    r = c.get("/api/applicant/health/capabilities")
    assert r.status_code == 401


def test_configured_non_admin_second_account_denied(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    app = _mount(user="someone-else", configured=True, admins=("owner",))
    c = TestClient(app)
    FakeEngine.response = _ALL_REAL
    r = c.get("/api/applicant/health/capabilities")
    assert r.status_code == 403


def test_configured_owner_allowed(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    app = _mount(user="owner", configured=True, admins=("owner",))
    c = TestClient(app)
    FakeEngine.response = _ALL_REAL
    r = c.get("/api/applicant/health/capabilities")
    assert r.status_code == 200
