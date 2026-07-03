"""Hermetic tests for the workspace feedback-history proxy (dark-engine audit item
23): GET /api/applicant/memory/feedback-history.

Feedback was write-only in the front door -- the user could decline a match with a
reason, or redline a generated résumé/answer, but never see what stuck. This proxy
forwards to the engine's new ``GET /api/feedback/{campaign_id}`` (backed by
``FeedbackSummaryProvider``). Same harness/conventions as
``test_applicant_memory_routes.py``: mount only ``routes.applicant_memory_routes``
on a bare FastAPI app and serve the engine with an ``httpx.MockTransport`` (zero
network).
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


def test_feedback_history_resolves_first_campaign():
    seen = {}

    def handler(request):
        if request.url.path == "/api/feedback/camp-1" and request.method == "GET":
            seen["path"] = request.url.path
            return httpx.Response(
                200,
                json={
                    "campaign_id": "camp-1",
                    "items": [{"run_id": "feedback-decline-1", "text": "reason", "topic": "t", "kind": "decline"}],
                },
            )
        return _route(request, {})

    client = _make_client(handler)
    resp = client.get("/api/applicant/memory/feedback-history")
    assert resp.status_code == 200
    assert seen["path"] == "/api/feedback/camp-1"
    body = resp.json()
    assert body["campaign_id"] == "camp-1"
    assert body["items"][0]["kind"] == "decline"


def test_feedback_history_honours_explicit_campaign():
    seen = {}

    def handler(request):
        if request.url.path == "/api/feedback/camp-X" and request.method == "GET":
            seen["hit"] = True
            return httpx.Response(200, json={"campaign_id": "camp-X", "items": []})
        return httpx.Response(500, json={"detail": "should not resolve via list"})

    client = _make_client(handler)
    resp = client.get(
        "/api/applicant/memory/feedback-history", params={"campaign_id": "camp-X"}
    )
    assert resp.status_code == 200
    assert seen.get("hit") is True
    assert resp.json()["campaign_id"] == "camp-X"


def test_feedback_history_engine_timeout_becomes_503():
    def handler(request):
        if request.url.path == "/api/feedback/camp-1":
            raise httpx.ReadTimeout("slow", request=request)
        return _route(request, {})

    client = _make_client(handler)
    resp = client.get("/api/applicant/memory/feedback-history")
    assert resp.status_code == 503


def test_feedback_history_no_campaign_yet_is_409():
    def handler(request):
        if request.url.path == "/healthz":
            return httpx.Response(200, json={"ok": True})
        if request.url.path == "/api/campaigns":
            return httpx.Response(200, json=[])
        return httpx.Response(500, json={"detail": "x"})

    client = _make_client(handler)
    resp = client.get("/api/applicant/memory/feedback-history")
    assert resp.status_code == 409


def test_feedback_history_engine_down_degrades_to_503():
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    client = _make_client(handler)
    resp = client.get("/api/applicant/memory/feedback-history")
    assert resp.status_code == 503
    assert "Traceback" not in resp.text
