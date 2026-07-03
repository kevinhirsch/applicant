"""Hermetic tests for the "learned site routines" proxy (dark-engine audit #45).

`routes/applicant_mind_routes.py` forwards induced per-ATS routines from the
engine's ``/api/admin/routines`` surface (the AWM self-improvement flywheel's
record of what worked on a given job site). These tests mount only that router
on a bare FastAPI app and serve the engine with an ``httpx.MockTransport`` (zero
network), exercising:

* the workspace -> engine URL/method mapping;
* the read requires a logged-in user (matching the memory/skills/lessons reads);
* graceful degradation when the engine is down (503, not a 500).

Mirrors ``test_applicant_mind_lessons.py``'s conventions exactly.
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
    if path == "/api/admin/routines":
        return httpx.Response(
            200,
            json={
                "routines": [
                    {
                        "domain": "greenhouse.io",
                        "step_count": 3,
                        "successes": 2,
                        "failures": 0,
                        "score": 2,
                        "source": "induced",
                    },
                ],
                "status": "live",
            },
        )
    return httpx.Response(404, json={"detail": "not found"})


def test_routines_proxied():
    client = _make_client(_ok_handler)
    r = client.get("/api/applicant/mind/routines")
    assert r.status_code == 200
    body = r.json()
    assert len(body["routines"]) == 1
    row = body["routines"][0]
    assert row["domain"] == "greenhouse.io"
    assert row["step_count"] == 3
    assert row["successes"] == 2


def test_routines_empty_is_well_formed():
    def _empty(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/healthz":
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(200, json={"routines": [], "status": "live"})

    client = _make_client(_empty)
    r = client.get("/api/applicant/mind/routines")
    assert r.status_code == 200
    assert r.json()["routines"] == []


def test_routines_require_login():
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

    r = client.get("/api/applicant/mind/routines")
    assert r.status_code in (401, 403)


def test_routines_degrades_when_engine_down():
    def _down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client = _make_client(_down)
    r = client.get("/api/applicant/mind/routines")
    assert r.status_code == 503
