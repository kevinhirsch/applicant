"""Hermetic tests for the Lane C chat/agent ↔ engine bridge.

Mounts only ``routes/applicant_chat_routes.py`` on a bare FastAPI app with a tiny
middleware that authenticates the request (the real global auth gate lives in
``app.py`` and is out of scope here). The engine is faked via a scripted
``FakeEngine`` patched in for ``ApplicantEngineClient`` (covers the happy paths
+ soft-degrade on unreachable). Zero network.

(This file used to also stand up a real :class:`ApplicantEngineClient` over an
``httpx.MockTransport`` to cover a trio of "safe remote job action" proxies
this router carried -- request-final-approval / resume-account-step /
resume-detection-step. Those proxies were dead code (dark-engine audit item 3,
§B1: no caller anywhere on the chat surface; the remote lane already owns the
identical actions end-to-end) and were removed from
``routes/applicant_chat_routes.py`` alongside their tests below.)
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.applicant_chat_routes as mod
from routes.applicant_chat_routes import setup_applicant_chat_routes
from src.applicant_engine import EngineError


# --- test app with a stand-in auth middleware -------------------------------


def _make_app(authed: bool = True) -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def _auth(request, call_next):
        request.state.current_user = "tester" if authed else None
        return await call_next(request)

    app.include_router(setup_applicant_chat_routes())
    return app


# --- a scripted fake engine -------------------------------------------------


class FakeEngine:
    """Stands in for ApplicantEngineClient as an async context manager.

    Each instance reads class-level scripted return values / exceptions so a test
    can configure behaviour before the route constructs the client.
    """

    available = True
    calls: list = []
    responses: dict = {}
    raises: dict = {}

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def _maybe(self, key, default=None):
        FakeEngine.calls.append(key)
        if key in FakeEngine.raises:
            raise FakeEngine.raises[key]
        return FakeEngine.responses.get(key, default)

    async def engine_available(self):
        FakeEngine.calls.append("engine_available")
        return FakeEngine.available

    async def list_campaigns(self):
        return await self._maybe("list_campaigns", [])

    async def create_campaign(self, name):
        FakeEngine.calls.append(("create_campaign", name))
        if "create_campaign" in FakeEngine.raises:
            raise FakeEngine.raises["create_campaign"]
        return FakeEngine.responses.get("create_campaign", {"id": "c1", "name": name})

    async def chat(self, body):
        FakeEngine.calls.append(("chat", body))
        if "chat" in FakeEngine.raises:
            raise FakeEngine.raises["chat"]
        return FakeEngine.responses.get("chat", {"message": "hi", "gaps": [], "proposed_changes": []})

    async def chat_confirm(self, body):
        FakeEngine.calls.append(("chat_confirm", body))
        if "chat_confirm" in FakeEngine.raises:
            raise FakeEngine.raises["chat_confirm"]
        return FakeEngine.responses.get("chat_confirm", {"committed": True})

    async def list_pending_actions(self, cid):
        FakeEngine.calls.append(("list_pending_actions", cid))
        if "list_pending_actions" in FakeEngine.raises:
            raise FakeEngine.raises["list_pending_actions"]
        return FakeEngine.responses.get("list_pending_actions", {"campaign_id": cid, "count": 0, "items": []})

    async def resolve_pending_action(self, aid):
        FakeEngine.calls.append(("resolve_pending_action", aid))
        if "resolve_pending_action" in FakeEngine.raises:
            raise FakeEngine.raises["resolve_pending_action"]
        return None


@pytest.fixture(autouse=True)
def _reset_fake():
    FakeEngine.available = True
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
    c = TestClient(_make_app(authed=False))
    assert c.get("/api/applicant/chat/status").status_code == 401


# --- status -----------------------------------------------------------------


def test_status_reports_engine_availability(client):
    FakeEngine.available = True
    r = client.get("/api/applicant/chat/status")
    assert r.status_code == 200
    assert r.json() == {"engine_available": True}

    FakeEngine.available = False
    assert client.get("/api/applicant/chat/status").json() == {"engine_available": False}


# --- campaigns --------------------------------------------------------------


def test_list_campaigns_passthrough(client):
    FakeEngine.responses["list_campaigns"] = [{"id": "c1", "name": "Roles"}]
    r = client.get("/api/applicant/chat/campaigns")
    assert r.status_code == 200
    body = r.json()
    assert body["engine_available"] is True
    assert body["campaigns"] == [{"id": "c1", "name": "Roles"}]


def test_list_campaigns_soft_degrades_when_engine_down(client):
    FakeEngine.raises["list_campaigns"] = EngineError("down", is_timeout=True)
    r = client.get("/api/applicant/chat/campaigns")
    assert r.status_code == 200
    assert r.json() == {"engine_available": False, "campaigns": []}


def test_create_campaign_requires_name(client):
    assert client.post("/api/applicant/chat/campaigns", json={"name": "   "}).status_code == 400


def test_create_campaign_ok(client):
    r = client.post("/api/applicant/chat/campaigns", json={"name": "Backend 2026"})
    assert r.status_code == 200
    assert r.json()["name"] == "Backend 2026"
    assert ("create_campaign", "Backend 2026") in FakeEngine.calls


# --- assistant chat ---------------------------------------------------------


def test_send_message_returns_engine_reply(client):
    FakeEngine.responses["chat"] = {
        "message": "Tell me your target titles.",
        "gaps": ["target roles / search criteria"],
        "proposed_changes": [],
    }
    r = client.post("/api/applicant/chat/message", json={"campaign_id": "c1", "message": "hello"})
    assert r.status_code == 200
    body = r.json()
    assert body["message"].startswith("Tell me")
    assert body["gaps"] == ["target roles / search criteria"]
    assert ("chat", {"campaign_id": "c1", "message": "hello"}) in FakeEngine.calls


def test_send_message_preserves_control_actions(client):
    # D3: the engine returns control_actions (criteria-refocus confirm affordance),
    # which the JS consumes (applicantChat.js). The scrub must pass them through —
    # shaped to the user-facing fields — not drop them.
    FakeEngine.responses["chat"] = {
        "message": "Bumping your salary floor reshapes the search.",
        "gaps": [],
        "proposed_changes": [],
        "control_actions": [
            {
                "kind": "criteria",
                "applied": False,
                "requires_confirmation": True,
                "ok": True,
                "detail": {"min_salary": 150000},
            }
        ],
    }
    r = client.post("/api/applicant/chat/message", json={"campaign_id": "c1", "message": "raise salary"})
    assert r.status_code == 200
    actions = r.json()["control_actions"]
    assert len(actions) == 1
    a = actions[0]
    assert a["kind"] == "criteria"
    assert a["requires_confirmation"] is True
    assert a["applied"] is False
    assert a["ok"] is True
    assert a["detail"] == {"min_salary": 150000}


def test_scrub_chat_reply_preserves_control_actions():
    from routes.applicant_chat_routes import _scrub_chat_reply

    out = _scrub_chat_reply(
        {
            "message": "ok",
            "gaps": [],
            "proposed_changes": [],
            "control_actions": [
                {
                    "kind": "criteria",
                    "applied": False,
                    "requires_confirmation": True,
                    "ok": True,
                    "detail": {"min_salary": 150000, "_internal": {"run_id": "secret"}},
                    "session_handle": "leak",
                }
            ],
        }
    )
    assert "control_actions" in out
    a = out["control_actions"][0]
    assert a["kind"] == "criteria"
    assert a["requires_confirmation"] is True
    # The internal session handle is dropped; only the user-facing fields remain.
    assert "session_handle" not in a
    # detail keeps the primitive summary fields but drops nested non-primitives.
    assert a["detail"]["min_salary"] == 150000
    assert "_internal" not in a["detail"]


def test_scrub_chat_reply_control_actions_default_empty():
    from routes.applicant_chat_routes import _scrub_chat_reply

    out = _scrub_chat_reply({"message": "hi"})
    assert out["control_actions"] == []


def test_send_message_validates_input(client):
    assert client.post("/api/applicant/chat/message", json={"campaign_id": "c1", "message": " "}).status_code == 400
    assert client.post("/api/applicant/chat/message", json={"campaign_id": "", "message": "hi"}).status_code == 400


def test_send_message_forwards_engine_http_error(client):
    FakeEngine.raises["chat"] = EngineError("bad", status=409, detail="needs confirm")
    r = client.post("/api/applicant/chat/message", json={"campaign_id": "c1", "message": "hi"})
    assert r.status_code == 409
    assert r.json()["detail"] == "needs confirm"


def test_send_message_maps_unreachable_to_503(client):
    FakeEngine.raises["chat"] = EngineError("conn refused")  # no status -> transport failure
    r = client.post("/api/applicant/chat/message", json={"campaign_id": "c1", "message": "hi"})
    assert r.status_code == 503


def test_confirm_change_passthrough(client):
    FakeEngine.responses["chat_confirm"] = {"committed": True, "name": "city", "value": "NYC"}
    r = client.post(
        "/api/applicant/chat/confirm",
        json={"campaign_id": "c1", "name": "city", "value": "NYC"},
    )
    assert r.status_code == 200
    assert r.json()["committed"] is True


# --- pending job actions ----------------------------------------------------


def test_list_pending_actions_passthrough(client):
    FakeEngine.responses["list_pending_actions"] = {
        "campaign_id": "c1",
        "count": 1,
        "items": [{"id": "a1", "kind": "final_approval", "title": "Approve", "application_id": "app1"}],
    }
    r = client.get("/api/applicant/chat/pending-actions/c1")
    assert r.status_code == 200
    body = r.json()
    assert body["engine_available"] is True
    assert body["count"] == 1
    assert body["items"][0]["kind"] == "final_approval"


def test_list_pending_actions_soft_degrades(client):
    FakeEngine.raises["list_pending_actions"] = EngineError("down")
    r = client.get("/api/applicant/chat/pending-actions/c1")
    assert r.status_code == 200
    body = r.json()
    assert body["engine_available"] is False
    assert body["items"] == []


def test_resolve_pending_action_ok(client):
    r = client.post("/api/applicant/chat/pending-actions/a1/resolve")
    assert r.status_code == 200
    assert r.json() == {"resolved": True, "action_id": "a1"}
    assert ("resolve_pending_action", "a1") in FakeEngine.calls


def test_resolve_pending_action_forwards_error(client):
    FakeEngine.raises["resolve_pending_action"] = EngineError("nope", status=404, detail="unknown")
    r = client.post("/api/applicant/chat/pending-actions/missing/resolve")
    assert r.status_code == 404


def test_dead_remote_action_routes_are_gone(client):
    """dark-engine audit item 3: the chat lane no longer carries its own copies
    of the remote lane's request-final-approval / resume-account-step /
    resume-detection-step actions -- they had zero callers on this surface."""
    for route in (
        "request-final-approval",
        "resume-account-step",
        "resume-detection-step",
    ):
        r = client.post(f"/api/applicant/chat/applications/app1/{route}")
        assert r.status_code == 404
