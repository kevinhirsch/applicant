"""Hermetic tests for the Applicant Compare proxy (routes/applicant_compare_routes.py).

Zero network: the engine is served entirely by an ``httpx.MockTransport`` injected
through the route module's construction seam (``_engine_client``). Covers the happy
path of every endpoint (correct engine path/method/body/params relay), the typed-error
degradation (timeout -> 504, unreachable -> 503, engine 5xx -> 502, engine 4xx —
e.g. the ``require_llm_configured`` gate — forwarded), and that auth is enforced.

Mirrors tests/test_applicant_email_routes.py.
"""

import json

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import routes.applicant_compare_routes as mod
from routes.applicant_compare_routes import (
    ApplicantEngineClient,
    setup_applicant_compare_routes,
)


def _mock_engine(handler):
    """A no-network ApplicantEngineClient backed by ``handler``."""
    return ApplicantEngineClient(
        base_url="http://api:8000", transport=httpx.MockTransport(handler)
    )


@pytest.fixture
def make_client(monkeypatch):
    def _factory(handler, *, authed=True):
        monkeypatch.setattr(mod, "_engine_client", lambda: _mock_engine(handler))

        app = FastAPI()

        @app.middleware("http")
        async def _auth(request: Request, call_next):
            if authed:
                request.state.current_user = "kevin"
            return await call_next(request)

        app.include_router(setup_applicant_compare_routes())
        return TestClient(app)

    return _factory


# -- happy paths -----------------------------------------------------------


def test_list_campaigns_relays(make_client):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        return httpx.Response(200, json=[{"id": "camp-1", "name": "Backend roles"}])

    client = make_client(handler)
    resp = client.get("/api/applicant/compare/campaigns")
    assert resp.status_code == 200
    assert resp.json() == {"campaigns": [{"id": "camp-1", "name": "Backend roles"}]}
    assert captured["path"] == "/api/campaigns"


def test_compare_applications_relays_body_and_returns_diff(make_client):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["method"] = request.method
        captured["body"] = json.loads(request.content.decode())
        captured["campaign"] = request.url.params.get("campaign_id")
        return httpx.Response(
            200,
            json={
                "entity_ids": ["a1", "a2"],
                "entity_labels": {"a1": "SWE", "a2": "SRE"},
                "dimensions": [
                    {"key": "status", "label": "Status",
                     "values": {"a1": "applied", "a2": "draft"},
                     "diff": "2 different statuses"},
                ],
                "summary": "Compared 2 applications across 1 dimensions.",
            },
        )

    client = make_client(handler)
    resp = client.post(
        "/api/applicant/compare/applications",
        json={"ids": ["a1", "a2"], "campaign_id": "camp-1"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["entity_ids"] == ["a1", "a2"]
    assert data["dimensions"][0]["diff"] == "2 different statuses"
    # The ids go as the JSON body list; the campaign id goes as a query param —
    # matching the engine's POST signature (bare list body + campaign_id param).
    assert captured["path"] == "/api/compare/applications"
    assert captured["method"] == "POST"
    assert captured["body"] == ["a1", "a2"]
    assert captured["campaign"] == "camp-1"


def test_compare_postings_relays_and_omits_campaign_when_absent(make_client):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content.decode())
        captured["has_campaign"] = "campaign_id" in request.url.params
        return httpx.Response(200, json={"entity_ids": ["p1", "p2"], "dimensions": []})

    client = make_client(handler)
    resp = client.post(
        "/api/applicant/compare/postings",
        json={"ids": ["p1", "p2"]},
    )
    assert resp.status_code == 200
    assert captured["path"] == "/api/compare/postings"
    assert captured["body"] == ["p1", "p2"]
    # No campaign supplied -> no query param sent at all.
    assert captured["has_campaign"] is False


# -- error degradation -----------------------------------------------------


def test_timeout_becomes_504(make_client):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    client = make_client(handler)
    resp = client.post(
        "/api/applicant/compare/applications", json={"ids": ["a1", "a2"]}
    )
    assert resp.status_code == 504


def test_connect_error_becomes_503(make_client):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client = make_client(handler)
    resp = client.post(
        "/api/applicant/compare/applications", json={"ids": ["a1", "a2"]}
    )
    assert resp.status_code == 503


def test_engine_5xx_becomes_502(make_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    client = make_client(handler)
    resp = client.post(
        "/api/applicant/compare/postings", json={"ids": ["p1", "p2"]}
    )
    assert resp.status_code == 502


def test_engine_llm_gate_4xx_is_forwarded(make_client):
    """No model connected -> engine's require_llm_configured 4xx passes through."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"detail": "Connect a model first."})

    client = make_client(handler)
    resp = client.post(
        "/api/applicant/compare/applications", json={"ids": ["a1", "a2"]}
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Connect a model first."


# -- auth ------------------------------------------------------------------


def test_unauthenticated_is_rejected(make_client):
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - never hit
        return httpx.Response(200, json={})

    client = make_client(handler, authed=False)
    resp = client.post(
        "/api/applicant/compare/applications", json={"ids": ["a1", "a2"]}
    )
    assert resp.status_code == 401
