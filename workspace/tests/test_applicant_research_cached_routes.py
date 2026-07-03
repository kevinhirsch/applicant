"""Hermetic tests for the cached-read research proxy (dark-engine audit item
38) — ``GET /api/applicant/research/{campaign_id}/cached``.

The engine's ``ResearchService.cached_report`` already returns an
already-paid-for report for free, but before this change nothing exposed a
cached-read at the router or proxy level — only ``run`` (which reruns/charges
on a miss) and ``budget``. This adds the thin, auth-protected, owner-scoped
proxy over the new engine route, mirroring
``test_applicant_research_routes.py``'s approach: a scripted ``FakeEngine`` for
behaviour + a real client over ``httpx.MockTransport`` for the exact engine
path. Zero network.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.applicant_research_routes as mod
from routes.applicant_research_routes import setup_applicant_research_routes
from src.applicant_engine import ApplicantEngineClient, EngineError


def _make_app(*, user="alice") -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def _auth(request, call_next):
        request.state.current_user = user
        return await call_next(request)

    app.include_router(setup_applicant_research_routes())
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

    async def research_cached(self, cid, query):
        FakeEngine.calls.append(("cached", cid, query))
        if "cached" in FakeEngine.raises:
            raise FakeEngine.raises["cached"]
        return FakeEngine.responses.get(
            "cached",
            {
                "campaign_id": cid,
                "budget_remaining": 2,
                "query": query,
                "summary": "A short brief.",
                "key_findings": ["Finding one."],
                "sources": [{"title": "Src", "url": "https://example.com"}],
                "cached": True,
                "unavailable": False,
                "reason": "",
            },
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


# --- auth / owner-isolation --------------------------------------------------


def test_unauthenticated_is_rejected(monkeypatch):
    """No caller-supplied owner is ever trusted: an unauthenticated request
    must never reach the engine, regardless of the campaign_id in the path."""
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    c = TestClient(_make_app(user=""))
    r = c.get("/api/applicant/research/c1/cached", params={"query": "x"})
    assert r.status_code == 401
    # Rejected before ever touching the engine.
    assert FakeEngine.calls == []


def test_authenticated_owner_allowed(client):
    assert client.get(
        "/api/applicant/research/c1/cached", params={"query": "x"}
    ).status_code == 200


# --- cached read --------------------------------------------------------------


def test_cached_passthrough(client):
    r = client.get("/api/applicant/research/c1/cached", params={"query": "Acme platform team"})
    assert r.status_code == 200
    body = r.json()
    assert body["summary"] == "A short brief."
    assert body["cached"] is True
    assert body["budget_remaining"] == 2
    assert ("cached", "c1", "Acme platform team") in FakeEngine.calls


def test_cached_rejects_empty_query_before_hitting_the_engine(client):
    r = client.get("/api/applicant/research/c1/cached", params={"query": "   "})
    assert r.status_code == 422
    assert FakeEngine.calls == []


def test_cached_forwards_engine_404_when_nothing_is_cached(client):
    FakeEngine.raises["cached"] = EngineError(
        "nope", status=404, detail="No cached report for this query"
    )
    r = client.get("/api/applicant/research/c1/cached", params={"query": "x"})
    assert r.status_code == 404
    assert r.json()["detail"] == "No cached report for this query"


def test_cached_forwards_unknown_campaign_404(client):
    FakeEngine.raises["cached"] = EngineError("nope", status=404, detail="Campaign not found")
    r = client.get("/api/applicant/research/c1/cached", params={"query": "x"})
    assert r.status_code == 404
    assert r.json()["detail"] == "Campaign not found"


def test_cached_forwards_engine_422(client):
    FakeEngine.raises["cached"] = EngineError("bad", status=422, detail="query must not be empty")
    r = client.get("/api/applicant/research/c1/cached", params={"query": "x"})
    assert r.status_code == 422
    assert r.json()["detail"] == "query must not be empty"


def test_cached_maps_unreachable_engine_to_503(client):
    FakeEngine.raises["cached"] = EngineError("conn refused")  # no status -> transport failure
    r = client.get("/api/applicant/research/c1/cached", params={"query": "x"})
    assert r.status_code == 503


# --- exact engine path over a real client + MockTransport --------------------


def _mock_transport_app(handler):
    class TransportEngine(ApplicantEngineClient):
        def __init__(self, *a, **k):
            super().__init__(base_url="http://api:8000", transport=httpx.MockTransport(handler))

    return _make_app(), TransportEngine


def test_cached_hits_exact_engine_path_and_forwards_the_query(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["method"] = request.method
        seen["query"] = request.url.params.get("query")
        return httpx.Response(
            200,
            json={
                "campaign_id": "c1",
                "budget_remaining": 1,
                "summary": "ok",
                "cached": True,
                "unavailable": False,
            },
        )

    app, engine_cls = _mock_transport_app(handler)
    monkeypatch.setattr(mod, "ApplicantEngineClient", engine_cls)
    c = TestClient(app)
    r = c.get("/api/applicant/research/c1/cached", params={"query": "Acme platform team"})
    assert r.status_code == 200
    assert seen["path"] == "/api/research/c1/cached"
    assert seen["method"] == "GET"
    assert seen["query"] == "Acme platform team"
