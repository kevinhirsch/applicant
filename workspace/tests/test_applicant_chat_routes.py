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


# --- the unified Job Assistant session (chat-unification pass) ---------------
#
# GET /session resolves/creates the per-user workspace session flagged by the
# ENGINE_SESSION_URL sentinel; POST /message with session_id persists the turn
# into it. The session manager is faked (the real one needs the workspace DB);
# under the hermetic DATABASE_URL the route's DB lookup fails fast and falls
# back to the manager's in-memory cache, which is exactly what these exercise.


class FakeSession:
    def __init__(self, id, owner, endpoint_url, name="Job assistant",
                 model="Job assistant", archived=False):
        self.id = id
        self.owner = owner
        self.endpoint_url = endpoint_url
        self.name = name
        self.model = model
        self.archived = archived


class FakeSessionManager:
    def __init__(self):
        self.sessions: dict = {}
        self.messages: dict = {}
        self.created: list = []

    def get_session(self, sid):
        if sid not in self.sessions:
            raise KeyError(sid)
        return self.sessions[sid]

    def create_session(self, session_id, name, endpoint_url, model, rag=False, owner=None):
        s = FakeSession(session_id, owner, endpoint_url, name=name, model=model)
        self.sessions[session_id] = s
        self.created.append(session_id)
        return s


    def add_message(self, sid, message):
        self.messages.setdefault(sid, []).append(message)


def _client_with_sm(monkeypatch, sm=None, authed=True):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    app = FastAPI()

    @app.middleware("http")
    async def _auth(request, call_next):
        request.state.current_user = "tester" if authed else None
        return await call_next(request)

    app.include_router(setup_applicant_chat_routes(session_manager=sm))
    return TestClient(app)


def test_session_bootstrap_creates_the_flagged_session(monkeypatch):
    sm = FakeSessionManager()
    c = _client_with_sm(monkeypatch, sm)
    r = c.get("/api/applicant/chat/session")
    assert r.status_code == 200
    data = r.json()
    assert data["created"] is True
    sid = data["session_id"]
    s = sm.sessions[sid]
    assert s.owner == "tester"
    assert s.endpoint_url == mod.ENGINE_SESSION_URL
    assert s.name == mod.ENGINE_SESSION_NAME
    assert s.model == mod.ENGINE_SESSION_MODEL


def test_session_bootstrap_reuses_the_existing_session(monkeypatch):
    sm = FakeSessionManager()
    c = _client_with_sm(monkeypatch, sm)
    first = c.get("/api/applicant/chat/session").json()
    second = c.get("/api/applicant/chat/session").json()
    assert second["session_id"] == first["session_id"]
    assert second["created"] is False
    assert len(sm.created) == 1


def test_session_bootstrap_ignores_foreign_and_ordinary_sessions(monkeypatch):
    """Another user's flagged session, and the caller's own ORDINARY chats,
    must never be handed out as the Job Assistant session."""
    sm = FakeSessionManager()
    sm.sessions["other"] = FakeSession("other", "someone-else", mod.ENGINE_SESSION_URL)
    sm.sessions["plain"] = FakeSession("plain", "tester", "http://localhost:1234/v1")
    c = _client_with_sm(monkeypatch, sm)
    data = c.get("/api/applicant/chat/session").json()
    assert data["session_id"] not in ("other", "plain")
    assert data["created"] is True


def test_session_bootstrap_without_manager_is_unavailable(monkeypatch):
    c = _client_with_sm(monkeypatch, sm=None)
    r = c.get("/api/applicant/chat/session")
    assert r.status_code == 503


def test_session_bootstrap_requires_auth(monkeypatch):
    c = _client_with_sm(monkeypatch, FakeSessionManager(), authed=False)
    assert c.get("/api/applicant/chat/session").status_code == 401


def test_send_message_with_session_persists_both_turns(monkeypatch):
    sm = FakeSessionManager()
    c = _client_with_sm(monkeypatch, sm)
    sid = c.get("/api/applicant/chat/session").json()["session_id"]
    FakeEngine.responses["chat"] = {
        "message": "Noted.",
        "gaps": ["portfolio"],
        "proposed_changes": [
            {"kind": "attribute", "name": "salary", "value": "100k",
             "requires_confirmation": True, "applied": False},
        ],
    }
    r = c.post(
        "/api/applicant/chat/message",
        json={"campaign_id": "c1", "message": "hello", "session_id": sid},
    )
    assert r.status_code == 200
    msgs = sm.messages[sid]
    assert [m.role for m in msgs] == ["user", "assistant"]
    assert msgs[0].content == "hello"
    assert msgs[1].content == "Noted."
    # The assistant turn carries the label + the scrubbed job-action payload
    # so the native renderer's decoration seam can rebuild the chips on a
    # history reload.
    meta = msgs[1].metadata
    assert meta["character_name"] == mod.ENGINE_SESSION_NAME
    assert meta["applicant"]["gaps"] == ["portfolio"]
    assert meta["applicant"]["proposed_changes"][0]["name"] == "salary"


def test_send_message_with_plain_reply_persists_without_applicant_metadata(monkeypatch):
    """No chips payload => no metadata.applicant key (the decoration seam
    only fires when there is something to decorate)."""
    sm = FakeSessionManager()
    c = _client_with_sm(monkeypatch, sm)
    sid = c.get("/api/applicant/chat/session").json()["session_id"]
    FakeEngine.responses["chat"] = {"message": "Just chatting."}
    r = c.post(
        "/api/applicant/chat/message",
        json={"campaign_id": "c1", "message": "hi", "session_id": sid},
    )
    assert r.status_code == 200
    meta = sm.messages[sid][1].metadata
    assert "applicant" not in meta


def test_send_message_rejects_foreign_or_ordinary_sessions(monkeypatch):
    """Owner-scoping: a session that isn't the caller's own sentinel-flagged
    Job Assistant session 404s BEFORE the engine is called."""
    sm = FakeSessionManager()
    sm.sessions["foreign"] = FakeSession("foreign", "someone-else", mod.ENGINE_SESSION_URL)
    sm.sessions["plain"] = FakeSession("plain", "tester", "http://localhost:1234/v1")
    c = _client_with_sm(monkeypatch, sm)
    for sid in ("foreign", "plain", "missing"):
        r = c.post(
            "/api/applicant/chat/message",
            json={"campaign_id": "c1", "message": "hi", "session_id": sid},
        )
        assert r.status_code == 404, sid
    assert not any(call[0] == "chat" for call in FakeEngine.calls if isinstance(call, tuple)), (
        "the engine must not be called for a rejected session"
    )
    assert sm.messages == {}


def test_send_message_without_session_id_skips_persistence(monkeypatch):
    """The session-less contract is unchanged: reply passes through, nothing
    is persisted anywhere."""
    sm = FakeSessionManager()
    c = _client_with_sm(monkeypatch, sm)
    r = c.post(
        "/api/applicant/chat/message",
        json={"campaign_id": "c1", "message": "hi"},
    )
    assert r.status_code == 200
    assert sm.messages == {}


def test_send_message_engine_error_persists_nothing(monkeypatch):
    """A failed engine turn must leave no half-written history — the user's
    bubble only persists alongside a real reply."""
    sm = FakeSessionManager()
    c = _client_with_sm(monkeypatch, sm)
    sid = c.get("/api/applicant/chat/session").json()["session_id"]
    FakeEngine.raises["chat"] = EngineError("down", status=None)
    r = c.post(
        "/api/applicant/chat/message",
        json={"campaign_id": "c1", "message": "hi", "session_id": sid},
    )
    assert r.status_code == 503
    assert sm.messages == {}
