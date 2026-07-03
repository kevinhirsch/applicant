"""Regression coverage: the campaigns/sources proxy passes the engine's ``live``
field through untouched (dark-engine audit item 65).

The workspace's ``GET /api/applicant/campaigns/{id}/sources`` route
(``routes/applicant_campaigns_routes.py``) is a thin, owner-scoped pass-through over
``ApplicantEngineClient.list_discovery_sources`` -- it forwards whatever ``items``
the engine returns without stripping fields. The engine's discovery-sources router
now adds a per-source ``live: bool`` (real board vs. offline sample/fake client) so
the front-door badge (``applicantCampaignSettings.js`` ``_liveBadge``) can tell a
user whether a source is returning real or synthetic data. This guards that a future
change to the proxy doesn't silently drop the field.

Mirrors the fixture/mocking style of ``test_applicant_campaigns_routes.py``.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.applicant_campaigns_routes as mod
from routes.applicant_campaigns_routes import setup_applicant_campaigns_routes


def _make_app() -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def _auth(request, call_next):
        request.state.current_user = "tester"
        return await call_next(request)

    app.include_router(setup_applicant_campaigns_routes())
    return app


class FakeEngine:
    calls: list = []
    campaigns: list = []
    sources: dict = {}

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def list_campaigns(self):
        return FakeEngine.campaigns

    async def list_discovery_sources(self, cid):
        FakeEngine.calls.append(("sources", cid))
        return FakeEngine.sources.get(cid, {"items": []})


@pytest.fixture(autouse=True)
def _reset_fake():
    FakeEngine.calls = []
    FakeEngine.campaigns = []
    FakeEngine.sources = {}
    yield


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    return TestClient(_make_app())


def test_live_field_passes_through_for_real_source(client):
    FakeEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    FakeEngine.sources = {
        "c1": {"items": [
            {"source_key": "jobspy:indeed", "enabled": True, "yield_stats": {}, "live": True},
        ]}
    }
    body = client.get("/api/applicant/campaigns/c1/sources").json()
    assert body["items"][0]["live"] is True


def test_live_field_passes_through_for_sample_source(client):
    FakeEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    FakeEngine.sources = {
        "c1": {"items": [
            {"source_key": "sample", "enabled": True, "yield_stats": {}, "live": False},
        ]}
    }
    body = client.get("/api/applicant/campaigns/c1/sources").json()
    assert body["items"][0]["live"] is False
    assert body["items"][0]["source_key"] == "sample"


def test_not_owned_still_returns_empty_items_not_proxied(client):
    # Sanity: owner-scoping still applies with the extra field in play -- an
    # unowned campaign never reaches the engine, so nothing about the new field
    # can leak either.
    FakeEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    body = client.get("/api/applicant/campaigns/c-evil/sources").json()
    assert body["items"] == []
    assert ("sources", "c-evil") not in FakeEngine.calls
