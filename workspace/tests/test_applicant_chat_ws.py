"""Hermetic tests for workspace-native chat streaming over a WebSocket.

Mounts ONLY ``routes/chat_ws_routes.py`` on a bare FastAPI app with a fake
``auth_manager`` on ``app.state`` (the real global auth gate never runs for
WebSocket scopes anyway) and drives the REAL ``src/agent_runs.py`` replay buffer
directly — no LLM, no DB, no network. This exercises the transport/buffer/resume
seam the FE consumes, which is what this env can run (the full chat pipeline has
heavier deps; those live-run tests are integration-gated).

Covers: auth rejects an unauthenticated upgrade; a foreign-owned session is
refused (owner-scope, mirroring the SSE path's ``_verify_session_owner``); the
socket relays the SAME agent_runs buffer as the SSE path then a terminal ``end``;
a reconnect ``resume`` offset replays only the buffered tail (gap-free/dupe-free);
the buffer survives a subscriber disconnect (durability); a subscribe to a run
that's already gone ends cleanly (FE then falls back / reloads history).
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import src.agent_runs as agent_runs
from routes import chat_ws_routes
from routes.chat_ws_routes import setup_chat_ws_routes


# --- fakes ------------------------------------------------------------------


class FakeAuth:
    def __init__(self, configured: bool, tokens: dict[str, str]):
        self.is_configured = configured
        self._tokens = tokens

    def get_username_for_token(self, token):
        return self._tokens.get(token)


def _make_app(*, configured=True, tokens=None) -> FastAPI:
    app = FastAPI()
    app.state.auth_manager = FakeAuth(configured, tokens or {})
    app.include_router(setup_chat_ws_routes())
    return app


def _cookie(token: str) -> dict:
    return {"cookie": f"applicant_session={token}"}


def _seed_run(session_id: str, events: list[str], *, status: str = "done") -> None:
    """Populate a terminal agent_runs replay buffer WITHOUT needing an event
    loop at setup time. ``subscribe`` replays the buffer then (for a non-running
    run) returns — exactly what a finished/detached run looks like on reconnect.
    """
    run = agent_runs._Run()
    run.buffer = list(events)
    run.status = status
    agent_runs._RUNS[session_id] = run


@pytest.fixture(autouse=True)
def _own_everything(monkeypatch):
    """Default: the authenticated user owns the session (ownership is covered by
    its own DB-mirroring function; here we isolate the transport)."""
    monkeypatch.setattr(chat_ws_routes, "_ws_user_owns_session", lambda user, sid: True)
    yield
    agent_runs._RUNS.clear()


_SSE = [
    'data: {"type": "model_info", "model": "m"}\n\n',
    'data: {"delta": "Hello"}\n\n',
    'data: {"delta": " world"}\n\n',
    "data: [DONE]\n\n",
]


# --- auth on upgrade --------------------------------------------------------


def test_unauthenticated_upgrade_is_rejected():
    app = _make_app(configured=True, tokens={})
    with TestClient(app) as c:
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect("/api/chat/ws"):
                pass  # server closes the handshake before accept


def test_foreign_owned_session_is_refused(monkeypatch):
    app = _make_app(configured=True, tokens={"tok": "bob"})
    # Bob is authenticated but does NOT own this session.
    monkeypatch.setattr(chat_ws_routes, "_ws_user_owns_session", lambda user, sid: False)
    _seed_run("s1", _SSE)
    with TestClient(app) as c:
        with c.websocket_connect("/api/chat/ws", headers=_cookie("tok")) as ws:
            ws.send_json({"type": "subscribe", "session": "s1"})
            msg = ws.receive_json()
            assert msg["type"] == "error"
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()


# --- stream relay (SSE parity) ----------------------------------------------


def test_owner_receives_the_full_buffer_then_end():
    app = _make_app(configured=True, tokens={"tok": "alice"})
    _seed_run("s1", _SSE)
    with TestClient(app) as c:
        with c.websocket_connect("/api/chat/ws", headers=_cookie("tok")) as ws:
            ws.send_json({"type": "subscribe", "session": "s1"})
            got = []
            while True:
                m = ws.receive_json()
                if m["type"] == "end":
                    break
                assert m["type"] == "chunk"
                got.append(m["data"])
            # Byte-identical to the SSE event strings the SSE path serves.
            assert got == _SSE
            # seq is the buffer index — monotonic from 0.
            # (end seq == number of buffered events)


def test_missing_run_ends_immediately_for_fallback():
    # No run for this (owned) session — subscribe yields nothing, the client gets
    # an immediate `end` and falls back / reloads history. Never hangs.
    app = _make_app(configured=True, tokens={"tok": "alice"})
    with TestClient(app) as c:
        with c.websocket_connect("/api/chat/ws", headers=_cookie("tok")) as ws:
            ws.send_json({"type": "subscribe", "session": "ghost"})
            m = ws.receive_json()
            assert m["type"] == "end"
            assert m["seq"] == 0


# --- reconnect resume (replay only the tail, gap-free / dupe-free) -----------


def test_resume_offset_replays_only_the_buffered_tail():
    app = _make_app(configured=True, tokens={"tok": "alice"})
    _seed_run("s1", _SSE)
    with TestClient(app) as c:
        # A reconnecting client that already consumed the first 2 events resumes
        # at offset 2 — it must see ONLY events[2:], not the whole buffer again.
        with c.websocket_connect("/api/chat/ws", headers=_cookie("tok")) as ws:
            ws.send_json({"type": "subscribe", "session": "s1", "resume": 2})
            got = []
            while True:
                m = ws.receive_json()
                if m["type"] == "end":
                    break
                got.append((m["seq"], m["data"]))
            assert got == [(2, _SSE[2]), (3, _SSE[3])]


def test_resume_beyond_buffer_yields_just_end():
    app = _make_app(configured=True, tokens={"tok": "alice"})
    _seed_run("s1", _SSE)
    with TestClient(app) as c:
        with c.websocket_connect("/api/chat/ws", headers=_cookie("tok")) as ws:
            ws.send_json({"type": "subscribe", "session": "s1", "resume": 99})
            m = ws.receive_json()
            assert m["type"] == "end"


# --- durability: the buffer survives a subscriber disconnect ----------------


def test_buffer_survives_a_subscriber_disconnect_and_replays_again():
    app = _make_app(configured=True, tokens={"tok": "alice"})
    _seed_run("s1", _SSE)
    with TestClient(app) as c:
        # First subscriber consumes the whole buffer, then disconnects.
        with c.websocket_connect("/api/chat/ws", headers=_cookie("tok")) as ws:
            ws.send_json({"type": "subscribe", "session": "s1"})
            first = []
            while True:
                m = ws.receive_json()
                if m["type"] == "end":
                    break
                first.append(m["data"])
            assert first == _SSE
        # A fresh reconnect still replays the retained buffer — dropping one
        # subscriber never dropped the run's replay log.
        with c.websocket_connect("/api/chat/ws", headers=_cookie("tok")) as ws2:
            ws2.send_json({"type": "subscribe", "session": "s1"})
            second = []
            while True:
                m = ws2.receive_json()
                if m["type"] == "end":
                    break
                second.append(m["data"])
            assert second == _SSE


# --- bad first frame --------------------------------------------------------


def test_non_subscribe_first_frame_is_rejected():
    app = _make_app(configured=True, tokens={"tok": "alice"})
    with TestClient(app) as c:
        with c.websocket_connect("/api/chat/ws", headers=_cookie("tok")) as ws:
            ws.send_json({"type": "hello"})
            m = ws.receive_json()
            assert m["type"] == "error"
