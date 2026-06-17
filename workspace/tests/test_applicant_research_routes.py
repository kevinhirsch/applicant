"""Hermetic tests for the manual deep-research ↔ engine proxy.

Covers the manual run + budget read, the auth/owner gate, and faithful
passthrough of the engine's contract: the 200 ``unavailable`` degraded payload
(channel off / budget exhausted), the 422 empty-query rejection, and a clean 503
on an unreachable engine. Same approach as the other applicant-route tests: a
scripted ``FakeEngine`` for behaviour + a real client over ``httpx.MockTransport``
for exact engine paths. Zero network.
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

    async def research_run(self, cid, body):
        FakeEngine.calls.append(("run", cid, body))
        if "run" in FakeEngine.raises:
            raise FakeEngine.raises["run"]
        return FakeEngine.responses.get(
            "run",
            {
                "campaign_id": cid,
                "budget_remaining": 2,
                "query": body.get("query"),
                "summary": "A short brief.",
                "key_findings": ["Finding one."],
                "sources": [{"title": "Src", "url": "https://example.com"}],
                "cached": False,
                "unavailable": False,
                "reason": "",
            },
        )

    async def research_budget(self, cid):
        FakeEngine.calls.append(("budget", cid))
        if "budget" in FakeEngine.raises:
            raise FakeEngine.raises["budget"]
        return FakeEngine.responses.get(
            "budget",
            {"campaign_id": cid, "available": True, "calls_made": 1, "budget_remaining": 2},
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


# --- auth -------------------------------------------------------------------


def test_unauthenticated_is_rejected(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    c = TestClient(_make_app(user=""))
    assert c.post("/api/applicant/research/c1/run", json={"query": "x"}).status_code == 401
    assert c.get("/api/applicant/research/c1/budget").status_code == 401


def test_authenticated_owner_allowed(client):
    assert client.post("/api/applicant/research/c1/run", json={"query": "x"}).status_code == 200
    assert client.get("/api/applicant/research/c1/budget").status_code == 200


# --- run --------------------------------------------------------------------


def test_run_passthrough(client):
    r = client.post(
        "/api/applicant/research/c1/run",
        json={"query": "Acme platform team", "company": "Acme", "role": "Backend Engineer"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["summary"] == "A short brief."
    assert body["key_findings"] == ["Finding one."]
    assert body["sources"][0]["url"] == "https://example.com"
    assert body["budget_remaining"] == 2
    # The body is forwarded with all fields the engine accepts.
    assert ("run", "c1", {
        "query": "Acme platform team",
        "company": "Acme",
        "role": "Backend Engineer",
        "context": None,
        "max_time": None,
        "force": False,
    }) in FakeEngine.calls


def test_run_rejects_empty_query(client):
    r = client.post("/api/applicant/research/c1/run", json={"query": "   "})
    assert r.status_code == 422
    # Rejected before any engine call.
    assert FakeEngine.calls == []


def test_run_forwards_engine_422(client):
    FakeEngine.raises["run"] = EngineError("bad", status=422, detail="query must not be empty")
    r = client.post("/api/applicant/research/c1/run", json={"query": "x"})
    assert r.status_code == 422
    assert r.json()["detail"] == "query must not be empty"


def test_run_passes_through_unavailable_payload(client):
    # Channel off / budget exhausted: engine returns 200 + unavailable, not an error.
    FakeEngine.responses["run"] = {
        "campaign_id": "c1",
        "budget_remaining": 0,
        "query": "x",
        "summary": "",
        "key_findings": [],
        "sources": [],
        "cached": False,
        "unavailable": True,
        "reason": "budget_exhausted",
    }
    r = client.post("/api/applicant/research/c1/run", json={"query": "x"})
    assert r.status_code == 200
    body = r.json()
    assert body["unavailable"] is True
    assert body["reason"] == "budget_exhausted"
    assert body["budget_remaining"] == 0


def test_run_maps_unreachable_to_503(client):
    FakeEngine.raises["run"] = EngineError("conn refused")  # no status -> transport failure
    r = client.post("/api/applicant/research/c1/run", json={"query": "x"})
    assert r.status_code == 503


def test_run_forwards_unknown_campaign_404(client):
    FakeEngine.raises["run"] = EngineError("nope", status=404, detail="Campaign not found")
    r = client.post("/api/applicant/research/c1/run", json={"query": "x"})
    assert r.status_code == 404
    assert r.json()["detail"] == "Campaign not found"


# --- budget -----------------------------------------------------------------


def test_budget_passthrough(client):
    r = client.get("/api/applicant/research/c1/budget")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True
    assert body["budget_remaining"] == 2
    assert body["engine_available"] is True


def test_budget_soft_degrades(client):
    FakeEngine.raises["budget"] = EngineError("down")
    r = client.get("/api/applicant/research/c1/budget")
    assert r.status_code == 200
    body = r.json()
    assert body["engine_available"] is False
    assert body["available"] is False
    assert body["budget_remaining"] == 0


# --- exact engine paths over a real client + MockTransport ------------------


def _mock_transport_app(handler):
    class TransportEngine(ApplicantEngineClient):
        def __init__(self, *a, **k):
            super().__init__(base_url="http://api:8000", transport=httpx.MockTransport(handler))

    return _make_app(), TransportEngine


def test_run_hits_exact_engine_path(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["method"] = request.method
        return httpx.Response(
            200,
            json={"campaign_id": "c1", "budget_remaining": 1, "summary": "ok", "unavailable": False},
        )

    app, engine_cls = _mock_transport_app(handler)
    monkeypatch.setattr(mod, "ApplicantEngineClient", engine_cls)
    c = TestClient(app)
    r = c.post("/api/applicant/research/c1/run", json={"query": "x"})
    assert r.status_code == 200
    assert seen["path"] == "/api/research/c1/run"
    assert seen["method"] == "POST"


def test_budget_hits_exact_engine_path(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["method"] = request.method
        return httpx.Response(
            200, json={"campaign_id": "c1", "available": True, "calls_made": 0, "budget_remaining": 3}
        )

    app, engine_cls = _mock_transport_app(handler)
    monkeypatch.setattr(mod, "ApplicantEngineClient", engine_cls)
    c = TestClient(app)
    r = c.get("/api/applicant/research/c1/budget")
    assert r.status_code == 200
    assert seen["path"] == "/api/research/c1/budget"
    assert seen["method"] == "GET"
