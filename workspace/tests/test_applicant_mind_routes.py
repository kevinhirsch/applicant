"""Hermetic tests for the workspace FR-MIND proxy (routes/applicant_mind_routes.py).

`routes/applicant_mind_routes.py` forwards "what the assistant remembers" + "saved
playbooks" + the learning-curation approvals to the engine's /api/agent-memory/*
surface. These tests mount only that router on a bare FastAPI app and serve the
engine with an ``httpx.MockTransport`` (zero network), exercising:

* the workspace -> engine URL/method mapping for every endpoint;
* reads require a logged-in user; approve/deny require the can_manage_memory privilege;
* graceful degradation when the engine is down (status reports not-ready);
* error translation (engine 404 forwarded as 404; timeout -> 503).

Auth is satisfied by a tiny middleware that sets ``request.state.current_user`` so
``require_user`` / ``require_privilege`` pass (privileges fail-open for a resolved
user, matching the rest of the Brain modal).
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


# --- handlers --------------------------------------------------------------

def _ok_handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/healthz":
        return httpx.Response(200, json={"status": "ok"})
    if path == "/api/agent-memory":
        return httpx.Response(
            200,
            json={
                "environment": [{"text": "Acme uses Workday", "kind": "environment",
                                 "scope": "global", "campaign_id": None}],
                "user": [{"text": "Prefers concise cover letters", "kind": "user",
                          "scope": "global", "campaign_id": None}],
                "truncated": False,
            },
        )
    if path == "/api/agent-memory/skills":
        return httpx.Response(200, json={"items": [{"name": "acme-workday",
                                                    "description": "Acme tenant flow"}]})
    if path == "/api/agent-memory/skills/acme-workday":
        return httpx.Response(200, json={"name": "acme-workday", "procedure": ["step one"]})
    if path == "/api/agent-memory/curation":
        return httpx.Response(200, json={"count": 1, "items": [
            {"id": "abc123", "type": "memory", "text": "Remember X"}]})
    if path == "/api/agent-memory/curation/abc123/approve":
        return httpx.Response(200, json={"ok": True, "id": "abc123"})
    if path == "/api/agent-memory/curation/abc123/deny":
        return httpx.Response(200, json={"ok": True, "id": "abc123"})
    return httpx.Response(404, json={"detail": "not found"})


def test_memory_snapshot_proxied():
    client = _make_client(_ok_handler)
    r = client.get("/api/applicant/mind/memory")
    assert r.status_code == 200
    body = r.json()
    assert body["environment"][0]["text"] == "Acme uses Workday"
    assert body["user"][0]["kind"] == "user"


def test_skills_list_and_detail_proxied():
    client = _make_client(_ok_handler)
    assert client.get("/api/applicant/mind/skills").json()["items"][0]["name"] == "acme-workday"
    detail = client.get("/api/applicant/mind/skills/acme-workday").json()
    assert detail["procedure"] == ["step one"]


def test_curation_list_and_approve_deny():
    client = _make_client(_ok_handler)
    assert client.get("/api/applicant/mind/curation").json()["count"] == 1
    assert client.post("/api/applicant/mind/curation/abc123/approve").json()["ok"] is True
    assert client.post("/api/applicant/mind/curation/abc123/deny").json()["ok"] is True


def test_status_ready_when_engine_up():
    client = _make_client(_ok_handler)
    body = client.get("/api/applicant/mind/status").json()
    assert body == {"ready": True, "engine_available": True}


def test_status_not_ready_when_engine_down():
    def _down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client = _make_client(_down)
    body = client.get("/api/applicant/mind/status").json()
    assert body["engine_available"] is False
    assert body["ready"] is False


def test_skill_detail_404_forwarded():
    def _missing(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/healthz":
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(404, json={"detail": "That saved playbook was not found."})

    client = _make_client(_missing)
    r = client.get("/api/applicant/mind/skills/nope")
    assert r.status_code == 404


def test_engine_timeout_becomes_503():
    def _timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    client = _make_client(_timeout)
    r = client.get("/api/applicant/mind/memory")
    assert r.status_code == 503
