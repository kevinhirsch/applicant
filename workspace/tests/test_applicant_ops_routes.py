"""Hermetic tests for the crit-ops operations ↔ engine proxy.

Covers the Update button, run-mode/throughput controls, and discovery-source
toggles. Same approach as the admin-route tests: a scripted ``FakeEngine`` for
behaviour + a real client over ``httpx.MockTransport`` for exact engine paths.
Zero network.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.applicant_ops_routes as mod
from routes.applicant_ops_routes import setup_applicant_ops_routes
from src.applicant_engine import ApplicantEngineClient, EngineError


class _AuthMgr:
    def __init__(self, *, configured, admins=None):
        self.is_configured = configured
        self._admins = admins or set()

    def is_admin(self, user):
        return user in self._admins


def _make_app(*, user="alice", configured=True, admins=("alice",)) -> FastAPI:
    app = FastAPI()
    app.state.auth_manager = _AuthMgr(configured=configured, admins=set(admins))

    @app.middleware("http")
    async def _auth(request, call_next):
        request.state.current_user = user
        return await call_next(request)

    app.include_router(setup_applicant_ops_routes())
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

    async def update_status(self):
        return await self._maybe("update_status", default={"surface": "update", "status": "live"})

    async def update_trigger(self):
        return await self._maybe("update_trigger", default={"started": False, "message": "Dry run"})

    async def agent_runs_list(self, cid):
        return await self._maybe("runs", cid, default={"campaign_id": cid, "count": 0, "items": []})

    async def agent_run_intent(self, cid):
        return await self._maybe("intent", cid, default={"campaign_id": cid, "intent": None})

    async def agent_run_configure(self, cid, body):
        FakeEngine.calls.append(("configure", cid, body))
        if "configure" in FakeEngine.raises:
            raise FakeEngine.raises["configure"]
        return FakeEngine.responses.get("configure", {"campaign_id": cid, "run_mode": body.get("run_mode"), "throughput_target": body.get("throughput_target"), "hard_cap": 30})

    async def discovery_sources_list(self, cid):
        return await self._maybe("sources", cid, default={"campaign_id": cid, "items": []})

    async def discovery_source_toggle(self, cid, key, enabled):
        FakeEngine.calls.append(("toggle", cid, key, enabled))
        if "toggle" in FakeEngine.raises:
            raise FakeEngine.raises["toggle"]
        return {"campaign_id": cid, "source_key": key, "enabled": enabled}

    async def _request(self, method, path, *, json=None, params=None):
        # The exploration-budget read/write (FR-LEARN-6) goes through the client's
        # request seam (the engine criteria/learning surface). Scripted via the
        # "signature"/"budget" keys; defaults to a benign read so the source list
        # still renders when no budget script is set.
        FakeEngine.calls.append(("_request", method, path, json, params))
        key = "budget" if method == "PUT" else "signature"
        if key in FakeEngine.raises:
            raise FakeEngine.raises[key]
        if key in FakeEngine.responses:
            return FakeEngine.responses[key]
        return {"exploration_budget": 0.1} if key == "signature" else {}


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


# --- auth -------------------------------------------------------------------


def test_non_admin_is_rejected(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    c = TestClient(_make_app(user="bob", admins=("alice",)))
    assert c.get("/api/applicant/ops/update").status_code == 403


def test_single_user_mode_allows_owner(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    c = TestClient(_make_app(user="", configured=False, admins=()))
    assert c.get("/api/applicant/ops/update").status_code == 200


# --- update -----------------------------------------------------------------


def test_update_status_passthrough(client):
    FakeEngine.responses["update_status"] = {"surface": "update", "status": "live"}
    r = client.get("/api/applicant/ops/update")
    assert r.status_code == 200
    assert r.json()["engine_available"] is True


def test_update_status_soft_degrades(client):
    FakeEngine.raises["update_status"] = EngineError("down")
    r = client.get("/api/applicant/ops/update")
    assert r.status_code == 200
    assert r.json() == {"engine_available": False}


def test_update_trigger_passthrough(client):
    FakeEngine.responses["update_trigger"] = {"started": True, "message": "Started update.sh --apply (background)."}
    r = client.post("/api/applicant/ops/update/trigger")
    assert r.status_code == 200
    body = r.json()
    assert body["started"] is True
    assert "--apply" in body["message"]


def test_update_trigger_maps_unreachable_to_503(client):
    FakeEngine.raises["update_trigger"] = EngineError("conn refused")
    r = client.post("/api/applicant/ops/update/trigger")
    assert r.status_code == 503


# --- run controls -----------------------------------------------------------


def test_list_runs_soft_degrades(client):
    FakeEngine.raises["runs"] = EngineError("down")
    r = client.get("/api/applicant/ops/runs/c1")
    assert r.status_code == 200
    body = r.json()
    assert body["engine_available"] is False
    assert body["items"] == []


def test_intent_passthrough(client):
    FakeEngine.responses["intent"] = {"campaign_id": "c1", "intent": "Looking for 3 senior backend roles today."}
    r = client.get("/api/applicant/ops/runs/c1/intent")
    assert r.status_code == 200
    assert "senior backend" in r.json()["intent"]


def test_configure_run_passthrough(client):
    r = client.put("/api/applicant/ops/runs/c1/config", json={"run_mode": "continuous", "throughput_target": 5})
    assert r.status_code == 200
    assert r.json()["throughput_target"] == 5
    assert ("configure", "c1", {"run_mode": "continuous", "throughput_target": 5, "schedule": None}) in FakeEngine.calls


def test_configure_run_rejects_bad_mode(client):
    r = client.put("/api/applicant/ops/runs/c1/config", json={"run_mode": "warp_speed"})
    assert r.status_code == 400


def test_configure_run_rejects_negative_target(client):
    r = client.put("/api/applicant/ops/runs/c1/config", json={"throughput_target": -1})
    assert r.status_code == 400


# --- discovery sources ------------------------------------------------------


def test_list_sources_passthrough(client):
    FakeEngine.responses["sources"] = {
        "campaign_id": "c1",
        "items": [{"source_key": "linkedin", "enabled": True, "yield_stats": {"found": 10, "viable": 4}}],
    }
    r = client.get("/api/applicant/ops/discovery/c1")
    assert r.status_code == 200
    assert r.json()["items"][0]["source_key"] == "linkedin"


def test_toggle_source_passthrough(client):
    r = client.put("/api/applicant/ops/discovery/c1/linkedin", json={"enabled": False})
    assert r.status_code == 200
    assert r.json()["enabled"] is False
    assert ("toggle", "c1", "linkedin", False) in FakeEngine.calls


def test_toggle_source_forwards_error(client):
    FakeEngine.raises["toggle"] = EngineError("nope", status=404, detail="unknown source")
    r = client.put("/api/applicant/ops/discovery/c1/unknown", json={"enabled": True})
    assert r.status_code == 404


# --- exploration budget (FR-LEARN-6) ---------------------------------------


def test_list_sources_carries_exploration_budget(client):
    FakeEngine.responses["sources"] = {"campaign_id": "c1", "items": []}
    FakeEngine.responses["signature"] = {"exploration_budget": 0.35, "signature": {}}
    r = client.get("/api/applicant/ops/discovery/c1")
    assert r.status_code == 200
    assert r.json()["exploration_budget"] == 0.35


def test_list_sources_omits_budget_when_signature_read_fails(client):
    FakeEngine.responses["sources"] = {"campaign_id": "c1", "items": []}
    FakeEngine.raises["signature"] = EngineError("no learning surface", status=404)
    r = client.get("/api/applicant/ops/discovery/c1")
    assert r.status_code == 200
    assert "exploration_budget" not in r.json()


def test_set_exploration_budget_passthrough(client):
    FakeEngine.responses["budget"] = {"campaign_id": "c1", "exploration_budget": 0.5}
    r = client.put("/api/applicant/ops/discovery/c1/exploration-budget", json={"exploration_budget": 0.5})
    assert r.status_code == 200
    assert r.json()["exploration_budget"] == 0.5


def test_set_exploration_budget_forwards_engine_400(client):
    FakeEngine.raises["budget"] = EngineError("bad", status=400, detail="Exploration budget must be between 0 and 1.")
    r = client.put("/api/applicant/ops/discovery/c1/exploration-budget", json={"exploration_budget": 5})
    assert r.status_code == 400


def test_exploration_budget_route_not_swallowed_as_source_key(client):
    # The specific exploration-budget route must win over the {source_key} catch-all.
    FakeEngine.responses["budget"] = {"campaign_id": "c1", "exploration_budget": 0.2}
    r = client.put("/api/applicant/ops/discovery/c1/exploration-budget", json={"exploration_budget": 0.2})
    assert r.status_code == 200
    # It went through _request (the budget path), not the source-toggle method.
    assert not any(c[0] == "toggle" for c in FakeEngine.calls)


# --- exact engine paths over a real client + MockTransport ------------------


def _mock_transport_app(handler):
    class TransportEngine(ApplicantEngineClient):
        def __init__(self, *a, **k):
            super().__init__(base_url="http://api:8000", transport=httpx.MockTransport(handler))

    return _make_app(), TransportEngine


def test_configure_hits_exact_engine_path(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["method"] = request.method
        return httpx.Response(200, json={"campaign_id": "c1", "run_mode": "continuous", "throughput_target": 5, "hard_cap": 30})

    app, engine_cls = _mock_transport_app(handler)
    monkeypatch.setattr(mod, "ApplicantEngineClient", engine_cls)
    c = TestClient(app)
    r = c.put("/api/applicant/ops/runs/c1/config", json={"run_mode": "continuous", "throughput_target": 5})
    assert r.status_code == 200
    assert seen["path"] == "/api/agent-runs/c1/config"
    assert seen["method"] == "PUT"


def test_toggle_hits_exact_engine_path(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["method"] = request.method
        return httpx.Response(200, json={"campaign_id": "c1", "source_key": "linkedin", "enabled": False})

    app, engine_cls = _mock_transport_app(handler)
    monkeypatch.setattr(mod, "ApplicantEngineClient", engine_cls)
    c = TestClient(app)
    r = c.put("/api/applicant/ops/discovery/c1/linkedin", json={"enabled": False})
    assert r.status_code == 200
    assert seen["path"] == "/api/discovery-sources/c1/linkedin"
    assert seen["method"] == "PUT"


def test_update_trigger_hits_exact_engine_path(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        return httpx.Response(200, json={"started": False, "message": "Dry run"})

    app, engine_cls = _mock_transport_app(handler)
    monkeypatch.setattr(mod, "ApplicantEngineClient", engine_cls)
    c = TestClient(app)
    r = c.post("/api/applicant/ops/update/trigger")
    assert r.status_code == 200
    assert seen["path"] == "/api/update/trigger"
