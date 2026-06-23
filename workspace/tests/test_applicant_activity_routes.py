"""Hermetic tests for the agent-activity proxy (surfacing-only).

Mounts only ``routes/applicant_activity_routes.py`` on a bare FastAPI app with a
tiny middleware that authenticates the request (the real global auth gate lives in
``app.py`` and is out of scope here). The engine is faked two ways:

* a scripted ``FakeEngine`` patched in for ``ApplicantEngineClient`` (covers the
  campaign resolution, the proxied shapes, and the soft-degrade paths), and
* a real :class:`ApplicantEngineClient` over an ``httpx.MockTransport`` proving the
  exact engine paths are hit.

Zero network either way.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.applicant_activity_routes as mod
from routes.applicant_activity_routes import setup_applicant_activity_routes
from src.applicant_engine import ApplicantEngineClient, EngineError


# --- test app with a stand-in auth middleware -------------------------------


def _make_app(authed: bool = True) -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def _auth(request, call_next):
        request.state.current_user = "tester" if authed else None
        return await call_next(request)

    app.include_router(setup_applicant_activity_routes())
    return app


# --- a scripted fake engine -------------------------------------------------


class FakeEngine:
    """Stands in for ApplicantEngineClient as an async context manager."""

    calls: list = []
    campaigns: list = []
    status: dict = {}          # campaign_id -> engine status payload
    intent: dict = {}          # campaign_id -> engine intent payload
    runs: dict = {}            # campaign_id -> engine runs payload
    snapshot: dict = {}        # campaign_id -> engine now/next/recent snapshot
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

    async def agent_run_status(self, cid):
        FakeEngine.calls.append(("agent_run_status", cid))
        if ("agent_run_status", cid) in FakeEngine.raises:
            raise FakeEngine.raises[("agent_run_status", cid)]
        return FakeEngine.status.get(cid, {})

    async def agent_run_intent(self, cid):
        FakeEngine.calls.append(("agent_run_intent", cid))
        if ("agent_run_intent", cid) in FakeEngine.raises:
            raise FakeEngine.raises[("agent_run_intent", cid)]
        return FakeEngine.intent.get(cid, {})

    async def agent_runs_list(self, cid):
        FakeEngine.calls.append(("agent_runs_list", cid))
        if ("agent_runs_list", cid) in FakeEngine.raises:
            raise FakeEngine.raises[("agent_runs_list", cid)]
        return FakeEngine.runs.get(cid, {"count": 0, "items": []})

    async def agent_status(self, cid):
        FakeEngine.calls.append(("agent_status", cid))
        if ("agent_status", cid) in FakeEngine.raises:
            raise FakeEngine.raises[("agent_status", cid)]
        return FakeEngine.snapshot.get(cid, {})


@pytest.fixture(autouse=True)
def _reset_fake():
    FakeEngine.calls = []
    FakeEngine.campaigns = []
    FakeEngine.status = {}
    FakeEngine.intent = {}
    FakeEngine.runs = {}
    FakeEngine.snapshot = {}
    FakeEngine.raises = {}
    yield


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    return TestClient(_make_app())


# --- auth -------------------------------------------------------------------


def test_unauthenticated_is_rejected(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    c = TestClient(_make_app(authed=False))
    for path in ("/status", "/intent", "/runs", "/snapshot"):
        r = c.get(f"/api/applicant/activity{path}")
        assert r.status_code == 401, path


# --- status -----------------------------------------------------------------


def test_status_proxies_first_campaign(client):
    FakeEngine.campaigns = [
        {"id": "c1", "name": "Backend"},
        {"id": "c2", "name": "Platform"},
    ]
    FakeEngine.status = {
        "c1": {
            "active": True,
            "run_mode": "continuous",
            "applied_today": 3,
            "latest_intent": "Scanning sources for new roles",
            "scheduler": {"running": True, "interval_seconds": 60},
        }
    }
    r = client.get("/api/applicant/activity/status")
    assert r.status_code == 200
    body = r.json()
    assert body["engine_available"] is True
    assert body["has_activity"] is True
    # First campaign wins, and its context is attached.
    assert body["campaign_id"] == "c1"
    assert body["campaign_name"] == "Backend"
    # The engine's own fields pass straight through.
    assert body["latest_intent"] == "Scanning sources for new roles"
    assert body["scheduler"]["running"] is True
    assert body["applied_today"] == 3
    # Only the first campaign's status is fetched.
    assert ("agent_run_status", "c1") in FakeEngine.calls
    assert ("agent_run_status", "c2") not in FakeEngine.calls


def test_status_soft_degrades_when_engine_down(client):
    FakeEngine.raises["list_campaigns"] = EngineError("down", is_timeout=True)
    r = client.get("/api/applicant/activity/status")
    assert r.status_code == 200
    assert r.json() == {"engine_available": False, "has_activity": False}


def test_status_no_activity_when_no_campaigns(client):
    FakeEngine.campaigns = []
    r = client.get("/api/applicant/activity/status")
    assert r.status_code == 200
    assert r.json() == {"engine_available": True, "has_activity": False}


def test_status_no_activity_when_status_fetch_errors(client):
    FakeEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    FakeEngine.raises[("agent_run_status", "c1")] = EngineError("boom", status=500)
    r = client.get("/api/applicant/activity/status")
    assert r.status_code == 200
    assert r.json() == {"engine_available": True, "has_activity": False}


# --- intent -----------------------------------------------------------------


def test_intent_proxies_sentence(client):
    FakeEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    FakeEngine.intent = {
        "c1": {"campaign_id": "c1", "intent": "Delivering a digest of 12 viable roles for your review"}
    }
    r = client.get("/api/applicant/activity/intent")
    assert r.status_code == 200
    body = r.json()
    assert body["engine_available"] is True
    assert body["has_activity"] is True
    assert body["intent"] == "Delivering a digest of 12 viable roles for your review"
    assert body["campaign_name"] == "Backend"


def test_intent_no_activity_when_intent_blank(client):
    FakeEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    FakeEngine.intent = {"c1": {"campaign_id": "c1", "intent": None}}
    r = client.get("/api/applicant/activity/intent")
    assert r.status_code == 200
    body = r.json()
    assert body["engine_available"] is True
    assert body["has_activity"] is False


def test_intent_soft_degrades_when_engine_down(client):
    FakeEngine.raises["list_campaigns"] = EngineError("down")
    r = client.get("/api/applicant/activity/intent")
    assert r.status_code == 200
    assert r.json() == {"engine_available": False, "has_activity": False, "intent": None}


# --- runs -------------------------------------------------------------------


def test_runs_proxies_history(client):
    FakeEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    FakeEngine.runs = {
        "c1": {
            "count": 2,
            "items": [
                {
                    "id": "r2",
                    "intent": "Delivering a digest of 12 viable roles for your review",
                    "run_mode": "continuous",
                    "stats": {"discovered": 5, "pipelines_started": 3, "completed": 1},
                },
                {
                    "id": "r1",
                    "intent": "Scanning sources for new roles",
                    "stats": {"discovered": 8},
                },
            ],
        }
    }
    r = client.get("/api/applicant/activity/runs")
    assert r.status_code == 200
    body = r.json()
    assert body["engine_available"] is True
    assert body["has_activity"] is True
    assert body["count"] == 2
    assert body["campaign_id"] == "c1"
    assert body["campaign_name"] == "Backend"
    # Latest first, engine fields intact.
    assert body["items"][0]["id"] == "r2"
    assert body["items"][0]["stats"]["pipelines_started"] == 3


def test_runs_handles_bare_list(client):
    # Engine may return a bare list rather than {count, items}; the proxy normalises.
    FakeEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    FakeEngine.runs = {"c1": [{"id": "r1", "intent": "Scanning sources for new roles"}]}
    r = client.get("/api/applicant/activity/runs")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["items"][0]["id"] == "r1"


def test_runs_no_activity_when_empty(client):
    FakeEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    FakeEngine.runs = {"c1": {"count": 0, "items": []}}
    r = client.get("/api/applicant/activity/runs")
    assert r.status_code == 200
    body = r.json()
    assert body["has_activity"] is False
    assert body["count"] == 0
    assert body["items"] == []


def test_runs_soft_degrades_when_engine_down(client):
    FakeEngine.raises["list_campaigns"] = EngineError("down", is_timeout=True)
    r = client.get("/api/applicant/activity/runs")
    assert r.status_code == 200
    assert r.json() == {
        "engine_available": False,
        "has_activity": False,
        "count": 0,
        "items": [],
    }


def test_runs_no_activity_when_no_campaigns(client):
    FakeEngine.campaigns = []
    r = client.get("/api/applicant/activity/runs")
    assert r.status_code == 200
    body = r.json()
    assert body == {
        "engine_available": True,
        "has_activity": False,
        "count": 0,
        "items": [],
    }


# --- snapshot (consolidated now / next / recent) ----------------------------


def test_snapshot_proxies_first_campaign(client):
    FakeEngine.campaigns = [
        {"id": "c1", "name": "Backend"},
        {"id": "c2", "name": "Platform"},
    ]
    FakeEngine.snapshot = {
        "c1": {
            "campaign_id": "c1",
            "now": {"running": True, "sentence": "Right now I'm working on your job search."},
            "next": {
                "sentence": "Next I'll deliver a digest of 12 viable roles for your review",
                "pending_actions": 2,
            },
            "recent": [{"role_name": "Backend Engineer", "status": "applied"}],
        }
    }
    r = client.get("/api/applicant/activity/snapshot")
    assert r.status_code == 200
    body = r.json()
    assert body["engine_available"] is True
    assert body["has_activity"] is True
    # First campaign wins; its label is attached.
    assert body["campaign_id"] == "c1"
    assert body["campaign_name"] == "Backend"
    # Engine blocks pass straight through.
    assert body["now"]["running"] is True
    assert body["next"]["pending_actions"] == 2
    assert body["recent"][0]["role_name"] == "Backend Engineer"
    # Only the first campaign's snapshot is fetched.
    assert ("agent_status", "c1") in FakeEngine.calls
    assert ("agent_status", "c2") not in FakeEngine.calls


def test_snapshot_soft_degrades_when_engine_down(client):
    FakeEngine.raises["list_campaigns"] = EngineError("down", is_timeout=True)
    r = client.get("/api/applicant/activity/snapshot")
    assert r.status_code == 200
    assert r.json() == {"engine_available": False, "has_activity": False}


def test_snapshot_no_activity_when_no_campaigns(client):
    FakeEngine.campaigns = []
    r = client.get("/api/applicant/activity/snapshot")
    assert r.status_code == 200
    assert r.json() == {"engine_available": True, "has_activity": False}


def test_snapshot_no_activity_when_fetch_errors(client):
    FakeEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    FakeEngine.raises[("agent_status", "c1")] = EngineError("boom", status=500)
    r = client.get("/api/applicant/activity/snapshot")
    assert r.status_code == 200
    assert r.json() == {"engine_available": True, "has_activity": False}


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

    app.include_router(setup_applicant_activity_routes())
    return app, TransportEngine


def test_status_hits_exact_engine_paths(monkeypatch):
    paths = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append((request.method, request.url.path))
        if request.url.path == "/api/campaigns":
            return httpx.Response(200, json=[{"id": "c9", "name": "Search"}])
        if request.url.path == "/api/agent-runs/c9/status":
            return httpx.Response(200, json={"active": True, "scheduler": {"running": True}})
        return httpx.Response(404, json={"detail": "unexpected"})

    app, engine_cls = _mock_transport_app(handler)
    monkeypatch.setattr(mod, "ApplicantEngineClient", engine_cls)
    c = TestClient(app)

    r = c.get("/api/applicant/activity/status")
    assert r.status_code == 200
    assert ("GET", "/api/campaigns") in paths
    assert ("GET", "/api/agent-runs/c9/status") in paths
    assert r.json()["campaign_name"] == "Search"


def test_runs_hits_exact_engine_path(monkeypatch):
    paths = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append((request.method, request.url.path))
        if request.url.path == "/api/campaigns":
            return httpx.Response(200, json=[{"id": "c9", "name": "Search"}])
        if request.url.path == "/api/agent-runs/c9":
            return httpx.Response(200, json={"count": 1, "items": [{"id": "r1", "intent": "x"}]})
        return httpx.Response(404, json={"detail": "unexpected"})

    app, engine_cls = _mock_transport_app(handler)
    monkeypatch.setattr(mod, "ApplicantEngineClient", engine_cls)
    c = TestClient(app)

    r = c.get("/api/applicant/activity/runs")
    assert r.status_code == 200
    assert ("GET", "/api/agent-runs/c9") in paths
    assert r.json()["count"] == 1


def test_snapshot_hits_exact_engine_path(monkeypatch):
    paths = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append((request.method, request.url.path))
        if request.url.path == "/api/campaigns":
            return httpx.Response(200, json=[{"id": "c9", "name": "Search"}])
        if request.url.path == "/api/agent/status/c9":
            return httpx.Response(200, json={"now": {"sentence": "x"}, "next": {}, "recent": []})
        return httpx.Response(404, json={"detail": "unexpected"})

    app, engine_cls = _mock_transport_app(handler)
    monkeypatch.setattr(mod, "ApplicantEngineClient", engine_cls)
    c = TestClient(app)

    r = c.get("/api/applicant/activity/snapshot")
    assert r.status_code == 200
    assert ("GET", "/api/agent/status/c9") in paths
    assert r.json()["campaign_name"] == "Search"
