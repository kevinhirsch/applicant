"""Hermetic tests for the Results proxy (surfacing-only, NON-admin).

Mounts only ``routes/applicant_results_routes.py`` on a bare FastAPI app with a
tiny middleware that authenticates the request (the real global auth gate lives in
``app.py`` and is out of scope here). The engine is faked two ways:

* a scripted ``FakeEngine`` patched in for ``ApplicantEngineClient`` (covers the
  campaign resolution, the proxied shape, and the soft-degrade / gate paths), and
* a real :class:`ApplicantEngineClient` over an ``httpx.MockTransport`` proving the
  exact engine paths are hit.

Zero network either way. Mirrors ``test_applicant_activity_routes.py``.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.applicant_results_routes as mod
from routes.applicant_results_routes import setup_applicant_results_routes
from src.applicant_engine import ApplicantEngineClient, EngineError


# --- test app with a stand-in auth middleware -------------------------------


def _make_app(authed: bool = True) -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def _auth(request, call_next):
        request.state.current_user = "tester" if authed else None
        return await call_next(request)

    app.include_router(setup_applicant_results_routes())
    return app


# --- a scripted fake engine -------------------------------------------------


class FakeEngine:
    """Stands in for ApplicantEngineClient as an async context manager."""

    calls: list = []
    campaigns: list = []
    learning: dict = {}        # campaign_id -> engine learning summary payload
    raises: dict = {}          # key -> EngineError

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def list_campaigns(self):
        FakeEngine.calls.append("list_campaigns")
        if "list_campaigns" in FakeEngine.raises:
            raise FakeEngine.raises["list_campaigns"]
        return FakeEngine.campaigns

    async def admin_learning(self, cid):
        FakeEngine.calls.append(("admin_learning", cid))
        if ("admin_learning", cid) in FakeEngine.raises:
            raise FakeEngine.raises[("admin_learning", cid)]
        return FakeEngine.learning.get(cid, {})


@pytest.fixture(autouse=True)
def _reset_fake():
    FakeEngine.calls = []
    FakeEngine.campaigns = []
    FakeEngine.learning = {}
    FakeEngine.raises = {}
    yield


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    return TestClient(_make_app())


def _learning_payload(cid: str) -> dict:
    return {
        "campaign_id": cid,
        "summary": {
            "total_matched": 40,
            "total_approved": 12,
            "total_submitted": 8,
            "sources_seen": 2,
        },
        "sources": [
            {"source": "greenhouse", "matched": 20, "approved": 8, "submitted": 6, "conversion_rate": 30.0},
            {"source": "lever", "matched": 20, "approved": 4, "submitted": 2, "conversion_rate": 10.0},
        ],
        "converting_roles": ["Backend Engineer", "Platform Engineer"],
        "converting_samples": 4,
        "exploration_budget": 0.2,
    }


# --- auth -------------------------------------------------------------------


def test_unauthenticated_is_rejected(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    c = TestClient(_make_app(authed=False))
    r = c.get("/api/applicant/results")
    assert r.status_code == 401


# --- owner-scoping: first campaign wins -------------------------------------


def test_proxies_first_campaign_learning(client):
    FakeEngine.campaigns = [
        {"id": "c1", "name": "Backend"},
        {"id": "c2", "name": "Platform"},
    ]
    FakeEngine.learning = {"c1": _learning_payload("c1")}
    r = client.get("/api/applicant/results")
    assert r.status_code == 200
    body = r.json()
    assert body["engine_available"] is True
    assert body["has_data"] is True
    # First campaign wins; its label is attached (owner-scoped resolution).
    assert body["campaign_id"] == "c1"
    assert body["campaign_name"] == "Backend"
    # Engine funnel + per-source + signature pass straight through.
    assert body["summary"]["total_matched"] == 40
    assert body["summary"]["total_submitted"] == 8
    assert body["sources"][0]["source"] == "greenhouse"
    assert body["sources"][0]["conversion_rate"] == 30.0
    assert body["converting_roles"] == ["Backend Engineer", "Platform Engineer"]
    assert body["converting_samples"] == 4
    # Only the first campaign's learning is fetched.
    assert ("admin_learning", "c1") in FakeEngine.calls
    assert ("admin_learning", "c2") not in FakeEngine.calls


# --- designed empty states ---------------------------------------------------


def test_no_data_when_no_campaigns(client):
    FakeEngine.campaigns = []
    r = client.get("/api/applicant/results")
    assert r.status_code == 200
    body = r.json()
    assert body["engine_available"] is True
    assert body["has_data"] is False
    assert body["summary"] == {}
    assert body["sources"] == []
    assert body["converting_roles"] == []


def test_no_data_when_zero_volume(client):
    # Reachable engine + a campaign, but a brand-new user with no volume yet.
    FakeEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    FakeEngine.learning = {
        "c1": {
            "campaign_id": "c1",
            "summary": {"total_matched": 0, "total_approved": 0, "total_submitted": 0},
            "sources": [],
            "converting_roles": [],
        }
    }
    r = client.get("/api/applicant/results")
    assert r.status_code == 200
    body = r.json()
    assert body["engine_available"] is True
    assert body["has_data"] is False


# --- soft-degrade: transport offline ----------------------------------------


def test_soft_degrades_when_engine_down_on_campaigns(client):
    FakeEngine.raises["list_campaigns"] = EngineError("down", is_timeout=True)
    r = client.get("/api/applicant/results")
    assert r.status_code == 200
    body = r.json()
    assert body["engine_available"] is False
    assert body.get("gated") is not True
    # Well-formed empty scaffold so the UI never chokes.
    assert body["summary"] == {}
    assert body["sources"] == []


def test_transport_error_on_learning_is_offline(client):
    FakeEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    FakeEngine.raises[("admin_learning", "c1")] = EngineError("down", status=None)
    r = client.get("/api/applicant/results")
    assert r.status_code == 200
    body = r.json()
    assert body["engine_available"] is False
    assert body.get("gated") is not True


# --- HONESTY: a setup gate is NOT offline -----------------------------------
#
# A setup gate (409, also 401/403/422) on either read must surface as GATED
# (gated:true + the engine's message, engine_available:true), NOT
# engine_available:false. The split is shared (src.applicant_engine.soft_degrade).

_GATE_MSG = (
    "Automated work is blocked until onboarding is complete and the model is configured."
)


def test_campaigns_409_gate_is_not_offline(client):
    FakeEngine.raises["list_campaigns"] = EngineError("gated", status=409, detail=_GATE_MSG)
    r = client.get("/api/applicant/results")
    assert r.status_code == 200
    body = r.json()
    assert body["gated"] is True
    assert body["engine_available"] is True
    assert body["message"] == _GATE_MSG
    assert body["summary"] == {}


def test_learning_403_gate_is_not_offline(client):
    FakeEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    FakeEngine.raises[("admin_learning", "c1")] = EngineError("gated", status=403, detail=_GATE_MSG)
    r = client.get("/api/applicant/results")
    assert r.status_code == 200
    body = r.json()
    assert body["gated"] is True
    assert body["engine_available"] is True
    assert body["message"] == _GATE_MSG
    # Campaign context still attached even on the gated learning read.
    assert body["campaign_id"] == "c1"
    assert body["campaign_name"] == "Backend"


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

    app.include_router(setup_applicant_results_routes())
    return app, TransportEngine


def test_results_hits_exact_engine_paths(monkeypatch):
    paths = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append((request.method, request.url.path))
        if request.url.path == "/api/campaigns":
            return httpx.Response(200, json=[{"id": "c9", "name": "Search"}])
        if request.url.path == "/api/admin/learning/c9":
            return httpx.Response(200, json=_learning_payload("c9"))
        return httpx.Response(404, json={"detail": "unexpected"})

    app, engine_cls = _mock_transport_app(handler)
    monkeypatch.setattr(mod, "ApplicantEngineClient", engine_cls)
    c = TestClient(app)

    r = c.get("/api/applicant/results")
    assert r.status_code == 200
    assert ("GET", "/api/campaigns") in paths
    assert ("GET", "/api/admin/learning/c9") in paths
    body = r.json()
    assert body["campaign_name"] == "Search"
    assert body["has_data"] is True
    assert body["sources"][0]["source"] == "greenhouse"
