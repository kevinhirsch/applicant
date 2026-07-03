"""Hermetic tests for the manual PII-retention sweep proxy (dark-engine audit #37).

``DataLifecycleService.prune_pii_older_than`` (#363) was previously reachable
ONLY from the dormant scheduler tick -- there was no admin-facing "run it now"
button. This proves the workspace side of the wired chain: ``POST
/api/applicant/admin/retention/prune`` is admin-gated (same gate as the rest of
``routes/applicant_admin_routes.py``), passes the real result straight through,
forwards engine write errors, and hits the exact engine path/method.

Same harness shape as ``test_applicant_admin_routes.py`` (a bare FastAPI app
mounting only ``setup_applicant_admin_routes()``), kept in its own file per this
lane's file-ownership boundary. Zero network either way.
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

    async def admin_run_retention_sweep(self, days=None):
        FakeEngine.calls.append(("retention_sweep", days))
        if "sweep" in FakeEngine.raises:
            raise FakeEngine.raises["sweep"]
        return FakeEngine.responses.get(
            "sweep",
            {"pruned": 0, "window_days": 0, "by_store": {}, "skipped": True, "requested_days": 0},
        )


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


# --- auth / scoping ---------------------------------------------------------


def test_non_admin_is_rejected(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    c = TestClient(_make_app(user="bob", configured=True, admins=("alice",)))
    assert c.post("/api/applicant/admin/retention/prune").status_code == 403
    assert FakeEngine.calls == []


def test_configured_unauthenticated_is_rejected(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    c = TestClient(_make_app(user=None, configured=True, admins=("alice",)))
    assert c.post("/api/applicant/admin/retention/prune").status_code == 401


def test_single_user_mode_allows_lone_owner(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    c = TestClient(_make_app(user="", configured=False, admins=()), client=("127.0.0.1", 51000))
    assert c.post("/api/applicant/admin/retention/prune").status_code == 200


def test_single_user_mode_refuses_remote(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    c = TestClient(_make_app(user="", configured=False, admins=()), client=("203.0.113.9", 40000))
    assert c.post("/api/applicant/admin/retention/prune").status_code == 401


# --- happy path / passthrough -----------------------------------------------


def test_sweep_passes_through_real_result(client):
    FakeEngine.responses["sweep"] = {
        "pruned": 2,
        "window_days": 30,
        "cutoff": "2026-01-01T00:00:00+00:00",
        "by_store": {"attributes": 1, "onboarding_profiles": 1},
        "requested_days": 30,
    }
    r = client.post("/api/applicant/admin/retention/prune")
    assert r.status_code == 200
    body = r.json()
    assert body["pruned"] == 2
    assert body["by_store"] == {"attributes": 1, "onboarding_profiles": 1}
    assert ("retention_sweep", None) in FakeEngine.calls


def test_sweep_no_op_skip_passes_through(client):
    r = client.post("/api/applicant/admin/retention/prune")
    assert r.status_code == 200
    assert r.json()["skipped"] is True


def test_sweep_maps_unreachable_engine_to_503(client):
    FakeEngine.raises["sweep"] = EngineError("conn refused")  # no status -> transport failure
    r = client.post("/api/applicant/admin/retention/prune")
    assert r.status_code == 503


def test_sweep_forwards_engine_4xx(client):
    FakeEngine.raises["sweep"] = EngineError("nope", status=409, detail="setup incomplete")
    r = client.post("/api/applicant/admin/retention/prune")
    assert r.status_code == 409
    assert r.json()["detail"] == "setup incomplete"


# --- exact engine path over a real client + MockTransport -------------------


def test_sweep_hits_exact_engine_path_and_method(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["method"] = request.method
        return httpx.Response(
            200,
            json={"pruned": 0, "window_days": 0, "by_store": {}, "skipped": True, "requested_days": 0},
        )

    class TransportEngine(ApplicantEngineClient):
        def __init__(self, *a, **k):
            super().__init__(base_url="http://api:8000", transport=httpx.MockTransport(handler))

    app = _make_app()
    monkeypatch.setattr(mod, "ApplicantEngineClient", TransportEngine)
    c = TestClient(app)
    r = c.post("/api/applicant/admin/retention/prune")
    assert r.status_code == 200
    assert seen["path"] == "/api/admin/retention/prune"
    assert seen["method"] == "POST"
