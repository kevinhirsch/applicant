"""Hermetic tests for the "learned lessons" proxy (dark-engine audit #44).

`routes/applicant_mind_routes.py` forwards Reflexion failure lessons from the
engine's ``/api/admin/lessons`` (+ ``/api/admin/lessons/{ats}``) surface. These
tests mount only that router on a bare FastAPI app and serve the engine with an
``httpx.MockTransport`` (zero network), exercising:

* the workspace -> engine URL/method mapping for the grouped-all and per-ATS reads;
* both reads require a logged-in user (matching the memory/skills/curation reads);
* graceful degradation when the engine is down (503, not a 500).
"""

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import routes.applicant_mind_routes as mindmod
from routes.applicant_mind_routes import setup_applicant_mind_routes
from src.applicant_engine import ApplicantEngineClient


def _make_client(handler, *, user="tester"):
    transport = httpx.MockTransport(handler)

    class _MockedClient(ApplicantEngineClient):
        def __init__(self, *a, **k):
            k["transport"] = transport
            k.setdefault("base_url", "http://api:8000")
            super().__init__(*a, **k)

    mindmod.ApplicantEngineClient = _MockedClient

    app = FastAPI()

    @app.middleware("http")
    async def _inject_user(request: Request, call_next):
        request.state.current_user = user
        return await call_next(request)

    app.include_router(setup_applicant_mind_routes())
    return TestClient(app)


@pytest.fixture(autouse=True)
def _restore_client():
    original = mindmod.ApplicantEngineClient
    yield
    mindmod.ApplicantEngineClient = original


def _ok_handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/healthz":
        return httpx.Response(200, json={"status": "ok"})
    if path == "/api/admin/lessons":
        return httpx.Response(
            200,
            json={
                "lessons": {
                    "greenhouse.io": [
                        {"ats": "greenhouse.io", "step": "resume_upload",
                         "lesson": "On greenhouse.io, the step 'resume_upload' "
                         "failed (locator not found); try an alternate selector "
                         "or pause for confirmation next time."},
                    ],
                },
                "status": "live",
            },
        )
    if path == "/api/admin/lessons/greenhouse.io":
        return httpx.Response(
            200,
            json={
                "ats": "greenhouse.io",
                "lessons": [
                    {"ats": "greenhouse.io", "step": "resume_upload",
                     "lesson": "On greenhouse.io, the step 'resume_upload' "
                     "failed (locator not found); try an alternate selector "
                     "or pause for confirmation next time."},
                ],
                "status": "live",
            },
        )
    if path == "/api/admin/lessons/unknown-ats.example":
        return httpx.Response(200, json={"ats": "unknown-ats.example", "lessons": [], "status": "live"})
    return httpx.Response(404, json={"detail": "not found"})


def test_all_lessons_proxied():
    client = _make_client(_ok_handler)
    r = client.get("/api/applicant/mind/lessons")
    assert r.status_code == 200
    body = r.json()
    assert "greenhouse.io" in body["lessons"]
    assert body["lessons"]["greenhouse.io"][0]["step"] == "resume_upload"


def test_lessons_for_ats_proxied():
    client = _make_client(_ok_handler)
    r = client.get("/api/applicant/mind/lessons/greenhouse.io")
    assert r.status_code == 200
    body = r.json()
    assert body["ats"] == "greenhouse.io"
    assert len(body["lessons"]) == 1
    assert "locator not found" in body["lessons"][0]["lesson"]


def test_lessons_for_unknown_ats_is_empty_not_error():
    client = _make_client(_ok_handler)
    r = client.get("/api/applicant/mind/lessons/unknown-ats.example")
    assert r.status_code == 200
    assert r.json()["lessons"] == []


def test_lessons_require_login():
    """No ``request.state.current_user`` -> require_user rejects (401/403)."""
    transport = httpx.MockTransport(_ok_handler)

    class _MockedClient(ApplicantEngineClient):
        def __init__(self, *a, **k):
            k["transport"] = transport
            k.setdefault("base_url", "http://api:8000")
            super().__init__(*a, **k)

    mindmod.ApplicantEngineClient = _MockedClient
    app = FastAPI()
    app.include_router(setup_applicant_mind_routes())
    client = TestClient(app)

    r = client.get("/api/applicant/mind/lessons")
    assert r.status_code in (401, 403)


def test_lessons_degrades_when_engine_down():
    def _down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client = _make_client(_down)
    r = client.get("/api/applicant/mind/lessons")
    assert r.status_code == 503
