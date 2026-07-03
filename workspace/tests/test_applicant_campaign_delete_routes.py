"""Hermetic tests for the campaign-delete proxy (dark-engine audit item 17).

The engine already implements ``DELETE /api/campaigns/{campaign_id}``
(``src/applicant/app/routers/campaigns.py``), routing through
``DataLifecycleService``/``ErasureService`` for a clean cross-store purge
(#363, FR-CRIT-4, NFR-PRIV-1). It had no workspace proxy, no client method,
and no UI -- a user could create job searches forever and never remove one.

This file pins the SOURCE-level shape + owner-scoping behaviour of the new
``DELETE /api/applicant/campaigns/{campaign_id}`` proxy in
``routes/applicant_campaigns_routes.py``, mirroring
``test_applicant_campaigns_routes.py``'s conventions for this exact module
(a scripted ``FakeEngine`` for the config/owner-scoping paths, plus a real
``ApplicantEngineClient`` over an ``httpx.MockTransport`` proving the exact
engine path is hit). The owner-isolation test is MANDATORY per this series'
DoD: a caller must never be able to delete a campaign they don't own.

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
    deleted: dict = {}   # campaign_id -> dict returned by delete
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

    async def delete_campaign(self, cid):
        FakeEngine.calls.append(("delete", cid))
        if ("delete", cid) in FakeEngine.raises:
            raise FakeEngine.raises[("delete", cid)]
        return FakeEngine.deleted.get(cid, {"deleted": True, "campaign_id": cid})


@pytest.fixture(autouse=True)
def _reset_fake():
    FakeEngine.calls = []
    FakeEngine.campaigns = []
    FakeEngine.deleted = {}
    FakeEngine.raises = {}
    yield


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    return TestClient(_make_app())


# --- auth ---------------------------------------------------------------


def test_unauthenticated_delete_is_rejected(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    c = TestClient(_make_app(authed=False))
    r = c.delete("/api/applicant/campaigns/c1")
    assert r.status_code == 401
    assert FakeEngine.calls == []


# --- delete (owner-scoped) -----------------------------------------------


def test_delete_proxies_when_owned(client):
    FakeEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    r = client.delete("/api/applicant/campaigns/c1")
    assert r.status_code == 200
    assert r.json()["deleted"] is True
    assert ("delete", "c1") in FakeEngine.calls


def test_delete_not_owned_is_404_not_proxied(client):
    """MANDATORY owner-isolation test: a caller must never be able to delete
    a campaign that isn't in their own campaign list -- mirrors
    test_patch_not_owned_is_404_not_proxied in test_applicant_campaigns_routes.py."""
    FakeEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    r = client.delete("/api/applicant/campaigns/c-evil")
    assert r.status_code == 404
    assert all(not (isinstance(call, tuple) and call[0] == "delete") for call in FakeEngine.calls)


def test_delete_engine_down_is_503(client):
    FakeEngine.raises["list_campaigns"] = EngineError("down")
    r = client.delete("/api/applicant/campaigns/c1")
    assert r.status_code == 503


def test_delete_engine_error_is_forwarded_with_engine_status(client):
    FakeEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    FakeEngine.raises[("delete", "c1")] = EngineError(
        "refused", status=422, detail="The system campaign cannot be deleted."
    )
    r = client.delete("/api/applicant/campaigns/c1")
    assert r.status_code == 422


# --- real client over MockTransport: exact engine path -------------------


def test_engine_delete_path_hit_over_real_client(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.setdefault("paths", []).append((request.method, request.url.path))
        if request.url.path == "/api/campaigns":
            return httpx.Response(200, json=[{"id": "c1", "name": "Backend"}])
        if request.url.path == "/api/campaigns/c1" and request.method == "DELETE":
            return httpx.Response(200, json={"deleted": True, "campaign_id": "c1"})
        return httpx.Response(404, json={"detail": "nope"})

    def _factory(*a, **k):
        return ApplicantEngineClient(base_url="http://api:8000", transport=httpx.MockTransport(handler))

    monkeypatch.setattr(mod, "ApplicantEngineClient", _factory)
    c = TestClient(_make_app())
    r = c.delete("/api/applicant/campaigns/c1")
    assert r.status_code == 200
    assert r.json()["deleted"] is True
    assert ("GET", "/api/campaigns") in captured["paths"]
    assert ("DELETE", "/api/campaigns/c1") in captured["paths"]


# --- engine client method --------------------------------------------------


def test_engine_client_exposes_delete_campaign():
    """The workspace's ApplicantEngineClient carries a delete_campaign method
    -- not an ad hoc inline request -- mirroring update_campaign."""
    assert hasattr(ApplicantEngineClient, "delete_campaign")


@pytest.mark.asyncio
async def test_engine_client_delete_campaign_hits_the_right_path():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "DELETE"
        assert request.url.path == "/api/campaigns/abc"
        return httpx.Response(200, json={"deleted": True})

    async with ApplicantEngineClient(
        base_url="http://api:8000", transport=httpx.MockTransport(handler)
    ) as engine:
        result = await engine.delete_campaign("abc")
        assert result == {"deleted": True}
