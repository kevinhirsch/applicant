"""Hermetic tests for the seeded-demo banner/clear proxy (P0-2, owner-scoped).

Mounts only ``routes/applicant_demo_routes.py`` on a bare FastAPI app with a
tiny middleware that authenticates the request (the real global auth gate lives
in ``app.py`` and is out of scope here). The engine is faked two ways:

* a scripted ``FakeEngine`` patched in for ``ApplicantEngineClient`` (covers the
  active/inactive/offline soft-degrade paths and the clear write), and
* a real :class:`ApplicantEngineClient` over an ``httpx.MockTransport`` proving
  the exact engine paths (``/api/dev/seed/status`` + ``/reset``) are hit.

Zero network either way.
"""

from __future__ import annotations

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.applicant_demo_routes as mod
from routes.applicant_demo_routes import setup_applicant_demo_routes
from src.applicant_engine import ApplicantEngineClient, EngineError


# --- test app with a stand-in auth middleware -------------------------------


def _make_app(authed: bool = True) -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def _auth(request, call_next):
        request.state.current_user = "tester" if authed else None
        return await call_next(request)

    app.include_router(setup_applicant_demo_routes())
    return app


# --- a scripted fake engine -------------------------------------------------


class FakeEngine:
    """Stands in for ApplicantEngineClient as an async context manager."""

    status_payload: dict = {}
    clear_payload: dict = {}
    status_raises: EngineError | None = None
    clear_raises: EngineError | None = None
    calls: list = []

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def demo_status(self):
        FakeEngine.calls.append("demo_status")
        if FakeEngine.status_raises is not None:
            raise FakeEngine.status_raises
        return FakeEngine.status_payload

    async def demo_clear(self):
        FakeEngine.calls.append("demo_clear")
        if FakeEngine.clear_raises is not None:
            raise FakeEngine.clear_raises
        return FakeEngine.clear_payload


def _reset_fake():
    FakeEngine.status_payload = {}
    FakeEngine.clear_payload = {}
    FakeEngine.status_raises = None
    FakeEngine.clear_raises = None
    FakeEngine.calls = []


# --- status ------------------------------------------------------------------


def test_status_active_passes_through(monkeypatch):
    _reset_fake()
    FakeEngine.status_payload = {
        "demo_active": True,
        "campaign_id": "demo-campaign",
        "counts": {"applications": 7, "postings": 7},
    }
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    r = TestClient(_make_app()).get("/api/applicant/demo/status")
    assert r.status_code == 200
    body = r.json()
    assert body["demo_active"] is True
    assert body["engine_available"] is True
    assert body["counts"] == {"applications": 7, "postings": 7}


def test_status_404_reads_as_not_in_demo_mode(monkeypatch):
    """The engine's seed router 404s when NOT in DEMO_MODE — the banner hides."""
    _reset_fake()
    FakeEngine.status_raises = EngineError("not found", status=404)
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    r = TestClient(_make_app()).get("/api/applicant/demo/status")
    assert r.status_code == 200
    body = r.json()
    assert body["demo_active"] is False
    # 404 == engine reachable, simply not in demo mode.
    assert body["engine_available"] is True


def test_status_offline_engine_soft_degrades(monkeypatch):
    _reset_fake()
    FakeEngine.status_raises = EngineError("boom", is_timeout=True)
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    r = TestClient(_make_app()).get("/api/applicant/demo/status")
    assert r.status_code == 200
    body = r.json()
    assert body["demo_active"] is False
    assert body["engine_available"] is False


def test_status_requires_owner(monkeypatch):
    _reset_fake()
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    r = TestClient(_make_app(authed=False)).get("/api/applicant/demo/status")
    assert r.status_code == 401


# --- clear -------------------------------------------------------------------


def test_clear_success(monkeypatch):
    _reset_fake()
    FakeEngine.clear_payload = {"reset": True, "counts": {"applications": 7}}
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    r = TestClient(_make_app()).post("/api/applicant/demo/clear")
    assert r.status_code == 200
    body = r.json()
    assert body["cleared"] is True
    assert body["counts"] == {"applications": 7}
    assert "demo_clear" in FakeEngine.calls


def test_clear_soft_degrades_when_not_in_demo_mode(monkeypatch):
    _reset_fake()
    FakeEngine.clear_raises = EngineError("not found", status=404)
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    r = TestClient(_make_app()).post("/api/applicant/demo/clear")
    assert r.status_code == 200
    body = r.json()
    assert body["cleared"] is False
    assert body["engine_available"] is True


def test_clear_requires_owner(monkeypatch):
    _reset_fake()
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    r = TestClient(_make_app(authed=False)).post("/api/applicant/demo/clear")
    assert r.status_code == 401
    # The engine must NOT be touched by an unauthenticated write.
    assert "demo_clear" not in FakeEngine.calls


# --- exact engine paths via a real client over MockTransport ----------------


def _mock_transport_app(handler):
    class TransportEngine(ApplicantEngineClient):
        def __init__(self, *a, **k):
            super().__init__(base_url="http://api:8000", transport=httpx.MockTransport(handler))

    app = FastAPI()

    @app.middleware("http")
    async def _auth(request, call_next):
        request.state.current_user = "tester"
        return await call_next(request)

    app.include_router(setup_applicant_demo_routes())
    return app, TransportEngine


def test_proxy_hits_exact_engine_paths(monkeypatch):
    paths = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append((request.method, request.url.path))
        if request.url.path == "/api/dev/seed/status":
            return httpx.Response(200, json={"demo_active": True, "counts": {}})
        if request.url.path == "/api/dev/seed/reset":
            return httpx.Response(200, json={"reset": True, "counts": {}})
        return httpx.Response(404, json={"detail": "unexpected"})

    app, engine_cls = _mock_transport_app(handler)
    monkeypatch.setattr(mod, "ApplicantEngineClient", engine_cls)
    c = TestClient(app)

    assert c.get("/api/applicant/demo/status").status_code == 200
    assert c.post("/api/applicant/demo/clear").status_code == 200
    assert ("GET", "/api/dev/seed/status") in paths
    assert ("POST", "/api/dev/seed/reset") in paths
