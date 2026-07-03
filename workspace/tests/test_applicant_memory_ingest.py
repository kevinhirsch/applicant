"""Hermetic tests for the workspace bulk-observation-import proxy.

`routes/applicant_memory_routes.py`'s ``POST /api/applicant/memory/ingest`` forwards
the "Tell it about yourself" paste box (workspace/static/js/applicantMind.js) to the
application engine's ``POST /api/feedback/{campaign_id}/ingest`` (dark-engine audit
item 42 — ``FeedbackService.ingest_parsed_input``'s bulk list path). Mirrors the
MockTransport pattern in test_applicant_memory_routes.py: mount only the memory
router, serve the engine with ``httpx.MockTransport`` (zero network), and exercise:

* the workspace -> engine URL/method/body mapping;
* campaign resolution (explicit id wins; otherwise the engine's first campaign);
* the response is passed straight through (applied/pending/conflicts/skipped);
* error translation (engine down -> 503; no campaign yet -> 409).
"""

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import routes.applicant_memory_routes as memmod
from routes.applicant_memory_routes import setup_applicant_memory_routes
from src.applicant_engine import ApplicantEngineClient


def _make_client(handler, *, user="tester"):
    transport = httpx.MockTransport(handler)

    class _MockedClient(ApplicantEngineClient):
        def __init__(self, *a, **k):
            k["transport"] = transport
            k.setdefault("base_url", "http://api:8000")
            super().__init__(*a, **k)

    memmod.ApplicantEngineClient = _MockedClient

    app = FastAPI()

    @app.middleware("http")
    async def _inject_user(request: Request, call_next):
        request.state.current_user = user
        return await call_next(request)

    app.include_router(setup_applicant_memory_routes())
    return TestClient(app)


@pytest.fixture(autouse=True)
def _restore_client():
    original = memmod.ApplicantEngineClient
    yield
    memmod.ApplicantEngineClient = original


def _route(request: httpx.Request, routes: dict):
    key = (request.method, request.url.path)
    if key in routes:
        return routes[key](request)
    if request.url.path == "/api/campaigns" and request.method == "GET":
        return httpx.Response(200, json=[{"id": "camp-1", "name": "Default"}])
    if request.url.path == "/healthz":
        return httpx.Response(200, json={"ok": True})
    return httpx.Response(404, json={"detail": f"unrouted {key}"})


def test_ingest_resolves_first_campaign_and_forwards_body():
    captured = {}

    def handler(request):
        if request.url.path == "/api/feedback/camp-1/ingest" and request.method == "POST":
            captured["body"] = request.content.decode()
            return httpx.Response(
                201,
                json={
                    "applied": ["location"],
                    "pending": [],
                    "conflicts": [],
                    "skipped": [],
                },
            )
        return _route(request, {})

    client = _make_client(handler)
    resp = client.post(
        "/api/applicant/memory/ingest",
        json={"observations": [{"name": "location", "value": "Austin, TX", "source": "paste"}]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["applied"] == ["location"]
    assert '"location"' in captured["body"] and '"Austin, TX"' in captured["body"]
    assert '"observations"' in captured["body"]


def test_ingest_honours_explicit_campaign():
    seen = {}

    def handler(request):
        if request.url.path == "/api/feedback/camp-X/ingest" and request.method == "POST":
            seen["hit"] = True
            return httpx.Response(201, json={"applied": [], "pending": [], "conflicts": [], "skipped": []})
        return httpx.Response(500, json={"detail": "should not resolve via list"})

    client = _make_client(handler)
    resp = client.post(
        "/api/applicant/memory/ingest",
        json={"campaign_id": "camp-X", "observations": [{"name": "a", "value": "b"}]},
    )
    assert resp.status_code == 200
    assert seen.get("hit") is True


def test_ingest_passes_through_pending_and_conflicts():
    def handler(request):
        if request.url.path == "/api/feedback/camp-1/ingest" and request.method == "POST":
            return httpx.Response(
                201,
                json={
                    "applied": ["github"],
                    "pending": [
                        {"name": "legal_name", "current_value": None, "proposed_value": "Jane", "is_integral": True}
                    ],
                    "conflicts": [
                        {"name": "location", "current_value": "NYC", "proposed_value": "Austin", "is_integral": False}
                    ],
                    "skipped": ["Gender"],
                },
            )
        return _route(request, {})

    client = _make_client(handler)
    resp = client.post(
        "/api/applicant/memory/ingest",
        json={
            "observations": [
                {"name": "github", "value": "octocat"},
                {"name": "legal_name", "value": "Jane"},
                {"name": "location", "value": "Austin"},
                {"name": "Gender", "value": "x"},
            ]
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["applied"] == ["github"]
    assert body["pending"][0]["name"] == "legal_name"
    assert body["conflicts"][0]["current_value"] == "NYC"
    assert body["skipped"] == ["Gender"]


def test_ingest_missing_campaign_is_409():
    def handler(request):
        if request.url.path == "/healthz":
            return httpx.Response(200, json={"ok": True})
        if request.url.path == "/api/campaigns":
            return httpx.Response(200, json=[])
        return httpx.Response(500, json={"detail": "x"})

    client = _make_client(handler)
    resp = client.post(
        "/api/applicant/memory/ingest",
        json={"observations": [{"name": "a", "value": "b"}]},
    )
    assert resp.status_code == 409


def test_ingest_engine_down_degrades_to_503():
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    client = _make_client(handler)
    resp = client.post(
        "/api/applicant/memory/ingest",
        json={"observations": [{"name": "a", "value": "b"}]},
    )
    assert resp.status_code == 503
    assert "Traceback" not in resp.text
