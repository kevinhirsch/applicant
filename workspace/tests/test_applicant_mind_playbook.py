"""Hermetic tests for the ACE playbook proxy (dark-engine audit item 46).

`routes/applicant_mind_routes.py` forwards structured add/revise/retire playbook
deltas to the engine's ``/api/agent-memory/playbooks/{ats}`` surface. These tests
mount only that router on a bare FastAPI app and serve the engine with an
``httpx.MockTransport`` (zero network), exercising:

* the workspace -> engine URL/method mapping for the read + apply-deltas endpoints;
* campaign resolution (an explicit ``campaign_id`` wins; otherwise the engine's
  first campaign, mirroring ``applicant_memory_routes.py``'s attribute-cloud
  resolution) and the 409 when no campaign exists yet;
* the read requires a logged-in user, the write requires ``can_manage_memory``;
* the write rejects an empty ``deltas`` list before ever reaching the engine;
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


_ENTRIES = {
    "ats": "workday.com",
    "campaign_id": "camp-1",
    "entries": [{"key": "wait-for-spinner", "text": "Wait for the spinner.",
                 "confidence": 0.5, "revision": 1}],
    "audit": [{"op": "add", "key": "wait-for-spinner", "text": "Wait for the spinner.",
               "applied_at": "2026-01-01T00:00:00+00:00"}],
}


def _ok_handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/healthz":
        return httpx.Response(200, json={"status": "ok"})
    if path == "/api/campaigns":
        return httpx.Response(200, json=[{"id": "camp-1", "name": "Default"}])
    if path == "/api/agent-memory/playbooks/workday.com":
        return httpx.Response(200, json=_ENTRIES)
    if path == "/api/agent-memory/playbooks/workday.com/apply-deltas":
        return httpx.Response(200, json={
            "ok": True, "ats": "workday.com", "campaign_id": "camp-1",
            "applied": [{"op": "add", "key": "wait-for-spinner", "text": "Wait for the spinner."}],
            "entries": _ENTRIES["entries"], "audit": _ENTRIES["audit"],
        })
    return httpx.Response(404, json={"detail": "not found"})


def test_playbook_read_resolves_default_campaign_and_proxies():
    client = _make_client(_ok_handler)
    r = client.get("/api/applicant/mind/playbooks/workday.com")
    assert r.status_code == 200
    body = r.json()
    assert body["entries"][0]["key"] == "wait-for-spinner"
    assert body["audit"][0]["op"] == "add"


def test_playbook_read_honors_explicit_campaign_id():
    seen_paths = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(str(request.url))
        return _ok_handler(request)

    client = _make_client(handler)
    r = client.get("/api/applicant/mind/playbooks/workday.com", params={"campaign_id": "camp-1"})
    assert r.status_code == 200
    # An explicit campaign_id must skip the /api/campaigns lookup entirely.
    assert not any("/api/campaigns" in p for p in seen_paths)


def test_playbook_read_without_any_campaign_is_409():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/healthz":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/api/campaigns":
            return httpx.Response(200, json=[])
        return httpx.Response(404, json={"detail": "not found"})

    client = _make_client(handler)
    r = client.get("/api/applicant/mind/playbooks/workday.com")
    assert r.status_code == 409


def test_playbook_read_requires_login():
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

    r = client.get("/api/applicant/mind/playbooks/workday.com")
    assert r.status_code in (401, 403)


def test_apply_deltas_proxied_with_payload():
    client = _make_client(_ok_handler)
    r = client.post(
        "/api/applicant/mind/playbooks/workday.com/apply-deltas",
        json={"campaign_id": "camp-1",
              "deltas": [{"op": "add", "key": "wait-for-spinner", "text": "Wait for the spinner."}]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["applied"][0]["key"] == "wait-for-spinner"


def test_apply_deltas_rejects_empty_delta_list_before_hitting_engine():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return _ok_handler(request)

    client = _make_client(handler)
    r = client.post(
        "/api/applicant/mind/playbooks/workday.com/apply-deltas",
        json={"campaign_id": "camp-1", "deltas": []},
    )
    assert r.status_code == 400
    assert not any("apply-deltas" in p for p in calls)


def test_apply_deltas_degrades_when_engine_down():
    def _down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client = _make_client(_down)
    r = client.post(
        "/api/applicant/mind/playbooks/workday.com/apply-deltas",
        json={"campaign_id": "camp-1", "deltas": [{"op": "add", "key": "k", "text": "t"}]},
    )
    assert r.status_code == 503


def test_playbook_read_degrades_when_engine_down():
    def _down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client = _make_client(_down)
    r = client.get("/api/applicant/mind/playbooks/workday.com")
    assert r.status_code == 503
