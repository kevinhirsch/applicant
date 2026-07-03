"""Hermetic tests for the campaign-clone proxy (dark-engine audit item 36).

``CampaignService.clone_campaign(source_id, name)`` (#301, FR-CRIT-4) already
duplicates a campaign's criteria/settings under a fresh identity -- the natural
"same search, new city" move. It had zero callers and no router, no workspace
proxy, no client method, and no UI. This file pins the SOURCE-level shape +
owner-scoping behaviour of the new ``POST /api/applicant/campaigns/{campaign_id}
/clone`` proxy in ``routes/applicant_campaigns_routes.py``, mirroring
``test_applicant_campaign_delete_routes.py``'s conventions for this exact
module (a scripted ``FakeEngine`` for the config/owner-scoping paths, plus a
real ``ApplicantEngineClient`` over an ``httpx.MockTransport`` proving the
exact engine path is hit). The owner-isolation test is MANDATORY per this
series' DoD: a caller must never be able to clone a campaign they don't own.

Each assertion here was hand-verified to go RED when its corresponding piece
of the wiring is reverted (dropping the route, dropping the owner-scoping
guard, dropping the client method), then confirmed GREEN again after
restoring.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.applicant_campaigns_routes as mod
from routes.applicant_campaigns_routes import setup_applicant_campaigns_routes
from src.applicant_engine import ApplicantEngineClient, EngineError


def _make_app(authed: bool = True) -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def _auth(request, call_next):
        request.state.current_user = "tester" if authed else None
        return await call_next(request)

    app.include_router(setup_applicant_campaigns_routes())
    return app


class FakeEngine:
    """Stands in for ApplicantEngineClient as an async context manager."""

    calls: list = []
    campaigns: list = []
    cloned: dict = {}   # campaign_id -> dict returned by clone
    raises: dict = {}    # key -> EngineError

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

    async def clone_campaign(self, cid, name):
        FakeEngine.calls.append(("clone", cid, name))
        if ("clone", cid) in FakeEngine.raises:
            raise FakeEngine.raises[("clone", cid)]
        return FakeEngine.cloned.get(
            cid, {"id": "clone-1", "name": name or "Copy", "run_mode": "continuous", "active": True}
        )


@pytest.fixture(autouse=True)
def _reset_fake():
    FakeEngine.calls = []
    FakeEngine.campaigns = []
    FakeEngine.cloned = {}
    FakeEngine.raises = {}
    yield


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    return TestClient(_make_app())


# --- auth ---------------------------------------------------------------


def test_unauthenticated_clone_is_rejected(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    c = TestClient(_make_app(authed=False))
    r = c.post("/api/applicant/campaigns/c1/clone", json={})
    assert r.status_code == 401
    assert FakeEngine.calls == []


# --- clone (owner-scoped) -----------------------------------------------


def test_clone_proxies_when_owned(client):
    FakeEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    r = client.post("/api/applicant/campaigns/c1/clone", json={"name": "Backend II"})
    assert r.status_code == 201
    assert r.json()["name"] == "Backend II"
    assert ("clone", "c1", "Backend II") in FakeEngine.calls


def test_clone_omitted_name_is_forwarded_as_none(client):
    """No name supplied -> the engine (not this proxy) decides the default name."""
    FakeEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    r = client.post("/api/applicant/campaigns/c1/clone", json={})
    assert r.status_code == 201
    assert ("clone", "c1", None) in FakeEngine.calls


def test_clone_not_owned_is_404_not_proxied(client):
    """MANDATORY owner-isolation test: a caller must never be able to clone
    a campaign that isn't in their own campaign list -- mirrors
    test_delete_not_owned_is_404_not_proxied in
    test_applicant_campaign_delete_routes.py."""
    FakeEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    r = client.post("/api/applicant/campaigns/c-evil/clone", json={"name": "steal"})
    assert r.status_code == 404
    assert all(not (isinstance(call, tuple) and call[0] == "clone") for call in FakeEngine.calls)


def test_clone_engine_down_is_503(client):
    FakeEngine.raises["list_campaigns"] = EngineError("down")
    r = client.post("/api/applicant/campaigns/c1/clone", json={})
    assert r.status_code == 503


def test_clone_engine_error_is_forwarded_with_engine_status(client):
    FakeEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    FakeEngine.raises[("clone", "c1")] = EngineError(
        "refused", status=422, detail="The system campaign cannot be cloned."
    )
    r = client.post("/api/applicant/campaigns/c1/clone", json={})
    assert r.status_code == 422


# --- real client over MockTransport: exact engine path -------------------


def test_engine_clone_path_hit_over_real_client(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.setdefault("paths", []).append((request.method, request.url.path))
        if request.url.path == "/api/campaigns":
            return httpx.Response(200, json=[{"id": "c1", "name": "Backend"}])
        if request.url.path == "/api/campaigns/c1/clone" and request.method == "POST":
            return httpx.Response(201, json={"id": "c2", "name": "Backend II"})
        return httpx.Response(404, json={"detail": "nope"})

    def _factory(*a, **k):
        return ApplicantEngineClient(base_url="http://api:8000", transport=httpx.MockTransport(handler))

    monkeypatch.setattr(mod, "ApplicantEngineClient", _factory)
    c = TestClient(_make_app())
    r = c.post("/api/applicant/campaigns/c1/clone", json={"name": "Backend II"})
    assert r.status_code == 201
    assert r.json()["id"] == "c2"
    assert ("GET", "/api/campaigns") in captured["paths"]
    assert ("POST", "/api/campaigns/c1/clone") in captured["paths"]


# --- engine client method --------------------------------------------------


def test_engine_client_exposes_clone_campaign():
    """The workspace's ApplicantEngineClient carries a clone_campaign method
    -- not an ad hoc inline request -- mirroring delete_campaign."""
    assert hasattr(ApplicantEngineClient, "clone_campaign")


@pytest.mark.asyncio
async def test_engine_client_clone_campaign_hits_the_right_path():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/campaigns/abc/clone"
        return httpx.Response(201, json={"id": "def", "name": "abc (copy)"})

    async with ApplicantEngineClient(
        base_url="http://api:8000", transport=httpx.MockTransport(handler)
    ) as engine:
        result = await engine.clone_campaign("abc")
        assert result == {"id": "def", "name": "abc (copy)"}


@pytest.mark.asyncio
async def test_engine_client_clone_campaign_forwards_a_supplied_name():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured["body"] = json.loads(request.content)
        return httpx.Response(201, json={"id": "def", "name": "New name"})

    async with ApplicantEngineClient(
        base_url="http://api:8000", transport=httpx.MockTransport(handler)
    ) as engine:
        await engine.clone_campaign("abc", "New name")
        assert captured["body"] == {"name": "New name"}
