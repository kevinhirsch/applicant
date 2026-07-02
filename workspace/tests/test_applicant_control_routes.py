"""Hermetic tests for the global pause / kill-switch ↔ engine proxy.

The control lane exposes a single owner-scoped kill-switch (``pause-all`` /
``resume-all``) that fans the engine's per-campaign pause/resume across every
campaign the owner has. Same approach as the sibling proxy tests: a scripted
``FakeEngine`` patched in for ``ApplicantEngineClient`` (covers auth,
owner-scoping via ``list_campaigns()``, the fan-out, and the soft-degrade paths),
plus a real client over ``httpx.MockTransport`` proving the exact engine paths are
hit. Zero network.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.applicant_control_routes as mod
from routes.applicant_control_routes import setup_applicant_control_routes
from src.applicant_engine import ApplicantEngineClient, EngineError


# --- test app with a stand-in auth middleware -------------------------------


class _AuthMgr:
    def __init__(self, *, configured):
        self.is_configured = configured


def _make_app(*, user="alice", configured=True) -> FastAPI:
    app = FastAPI()
    app.state.auth_manager = _AuthMgr(configured=configured)

    @app.middleware("http")
    async def _auth(request, call_next):
        request.state.current_user = user
        return await call_next(request)

    app.include_router(setup_applicant_control_routes())
    return app


# --- a scripted fake engine -------------------------------------------------


class FakeEngine:
    """Stands in for ApplicantEngineClient as an async context manager."""

    calls: list = []
    campaigns: list = []
    raises: dict = {}          # key -> EngineError; keys: "list_campaigns",
    #                            ("pause", cid), ("resume", cid)

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

    async def agent_run_pause(self, cid):
        FakeEngine.calls.append(("pause", cid))
        if ("pause", cid) in FakeEngine.raises:
            raise FakeEngine.raises[("pause", cid)]
        return {"campaign_id": cid, "active": False, "paused": True}

    async def agent_run_resume(self, cid):
        FakeEngine.calls.append(("resume", cid))
        if ("resume", cid) in FakeEngine.raises:
            raise FakeEngine.raises[("resume", cid)]
        return {"campaign_id": cid, "active": True, "paused": False}


@pytest.fixture(autouse=True)
def _reset():
    FakeEngine.calls = []
    FakeEngine.campaigns = []
    FakeEngine.raises = {}
    yield


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    return TestClient(_make_app())


# --- auth -------------------------------------------------------------------


def test_pause_all_requires_auth(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    # No current user + configured auth manager → require_user rejects with 401,
    # even though the middleware ran (defence in depth).
    c = TestClient(_make_app(user=None, configured=True))
    assert c.post("/api/applicant/control/pause-all").status_code == 401
    assert c.post("/api/applicant/control/resume-all").status_code == 401


def test_authed_owner_is_allowed(client):
    FakeEngine.campaigns = [{"id": "c1"}]
    assert client.post("/api/applicant/control/pause-all").status_code == 200


# --- fan-out ----------------------------------------------------------------


def test_pause_all_fans_out_over_every_campaign(client):
    FakeEngine.campaigns = [{"id": "c1", "name": "Backend"}, {"id": "c2"}, {"id": "c3"}]
    r = client.post("/api/applicant/control/pause-all")
    assert r.status_code == 200
    body = r.json()
    assert body["paused"] is True
    assert body["campaigns"] == 3
    assert body["failed"] == []
    # It listed the owner's campaigns, then paused each one.
    assert FakeEngine.calls[0] == "list_campaigns"
    assert ("pause", "c1") in FakeEngine.calls
    assert ("pause", "c2") in FakeEngine.calls
    assert ("pause", "c3") in FakeEngine.calls


def test_resume_all_fans_out_over_every_campaign(client):
    FakeEngine.campaigns = [{"id": "c1"}, {"id": "c2"}]
    r = client.post("/api/applicant/control/resume-all")
    assert r.status_code == 200
    body = r.json()
    assert body["paused"] is False
    assert body["campaigns"] == 2
    assert ("resume", "c1") in FakeEngine.calls
    assert ("resume", "c2") in FakeEngine.calls
    # Never crosses lanes into pause.
    assert not any(c[0] == "pause" for c in FakeEngine.calls if isinstance(c, tuple))


def test_only_owner_scoped_campaigns_are_touched(client):
    # The proxy fans out over exactly what list_campaigns() (owner-scoped on the
    # engine) returns — nothing more.
    FakeEngine.campaigns = [{"id": "mine"}]
    client.post("/api/applicant/control/pause-all")
    paused = [c for c in FakeEngine.calls if isinstance(c, tuple) and c[0] == "pause"]
    assert paused == [("pause", "mine")]


def test_no_campaigns_is_a_noop_success(client):
    FakeEngine.campaigns = []
    r = client.post("/api/applicant/control/pause-all")
    assert r.status_code == 200
    body = r.json()
    assert body["engine_available"] is True
    assert body["campaigns"] == 0
    assert body["failed"] == []
    assert not any(isinstance(c, tuple) for c in FakeEngine.calls)


def test_ids_without_id_are_skipped(client):
    FakeEngine.campaigns = [{"id": "c1"}, {"name": "no-id"}, {}, "junk"]
    client.post("/api/applicant/control/pause-all")
    paused = [c for c in FakeEngine.calls if isinstance(c, tuple)]
    assert paused == [("pause", "c1")]


# --- partial failure --------------------------------------------------------


def test_one_campaign_failure_does_not_abort_the_sweep(client):
    FakeEngine.campaigns = [{"id": "c1"}, {"id": "c2"}, {"id": "c3"}]
    FakeEngine.raises[("pause", "c2")] = EngineError("busy", status=500)
    r = client.post("/api/applicant/control/pause-all")
    assert r.status_code == 200
    body = r.json()
    # c1 and c3 still paused; c2 reported as failed; overall not fully paused.
    assert body["paused"] is False
    assert body["campaigns"] == 2
    assert body["failed"] == ["c2"]
    assert ("pause", "c3") in FakeEngine.calls


def test_resume_reports_still_paused_on_partial_failure(client):
    FakeEngine.campaigns = [{"id": "c1"}, {"id": "c2"}]
    FakeEngine.raises[("resume", "c1")] = EngineError("busy", status=500)
    r = client.post("/api/applicant/control/resume-all")
    assert r.status_code == 200
    body = r.json()
    assert body["paused"] is True   # something is still paused
    assert body["failed"] == ["c1"]


# --- campaign-read soft degrade (gated vs offline) --------------------------


def test_pause_all_gate_409_is_not_offline(client):
    FakeEngine.raises["list_campaigns"] = EngineError(
        "gated", status=409, detail="Finish onboarding first."
    )
    r = client.post("/api/applicant/control/pause-all")
    assert r.status_code == 200
    body = r.json()
    assert body["gated"] is True
    assert body["engine_available"] is True
    assert body["message"] == "Finish onboarding first."
    # Nothing was paused.
    assert not any(isinstance(c, tuple) for c in FakeEngine.calls)


def test_pause_all_transport_error_is_offline(client):
    FakeEngine.raises["list_campaigns"] = EngineError("conn refused", status=None)
    r = client.post("/api/applicant/control/pause-all")
    assert r.status_code == 200
    body = r.json()
    assert body["engine_available"] is False
    assert body.get("gated") is not True


# --- exact engine paths over a real client + MockTransport ------------------


def _mock_transport_app(handler):
    class TransportEngine(ApplicantEngineClient):
        def __init__(self, *a, **k):
            super().__init__(base_url="http://api:8000", transport=httpx.MockTransport(handler))

    return _make_app(), TransportEngine


def test_pause_all_hits_exact_engine_paths(monkeypatch):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        if request.url.path == "/api/campaigns":
            return httpx.Response(200, json=[{"id": "c1"}, {"id": "c2"}])
        return httpx.Response(200, json={"campaign_id": "x", "paused": True})

    app, engine_cls = _mock_transport_app(handler)
    monkeypatch.setattr(mod, "ApplicantEngineClient", engine_cls)
    c = TestClient(app)
    r = c.post("/api/applicant/control/pause-all")
    assert r.status_code == 200
    assert ("GET", "/api/campaigns") in seen
    assert ("POST", "/api/agent-runs/c1/pause") in seen
    assert ("POST", "/api/agent-runs/c2/pause") in seen


def test_resume_all_hits_exact_engine_paths(monkeypatch):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        if request.url.path == "/api/campaigns":
            return httpx.Response(200, json=[{"id": "c1"}])
        return httpx.Response(200, json={"campaign_id": "c1", "active": True})

    app, engine_cls = _mock_transport_app(handler)
    monkeypatch.setattr(mod, "ApplicantEngineClient", engine_cls)
    c = TestClient(app)
    r = c.post("/api/applicant/control/resume-all")
    assert r.status_code == 200
    assert ("POST", "/api/agent-runs/c1/resume") in seen
