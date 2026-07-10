"""Hermetic tests for the deep-research progress stream over a WebSocket.

Mounts ONLY ``routes/research_ws_routes.py`` on a bare FastAPI app with a fake
``auth_manager`` on ``app.state`` (the real global auth gate never runs for
WebSocket scopes anyway) and drives a scripted fake research handler — no LLM, no
search deps, no DB, no network. This exercises the transport / owner-scope /
event-shape seam the FE consumes, which is what this env can run (the real
deep-research pipeline pulls heavier optional deps and is integration-gated).

Covers: auth rejects an unauthenticated upgrade; a foreign-owned session is
refused (owner-scope, mirroring the SSE path's ``_owns_in_memory`` — both call
``research_owns``); the socket relays the SAME payloads the SSE route serves
(``research_event_payloads``) as ``event`` frames then a terminal ``end``; a
progress→terminal sequence streams in order; an unknown session yields a single
``not_found`` event then ``end`` (the FE finishes the job / falls back — never a
silent dead UI); a terminal ``error`` carries the error message; the ``resume``
offset skips already-delivered seqs; a bad first frame is rejected.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from routes import research_ws_routes
from routes.research_ws_routes import setup_research_ws_routes
# Import the dependency-light shared module (NOT routes.research_routes, whose
# heavy DB imports need a data dir) — the WS relay uses these same helpers.
import routes.research_stream as research_stream


# --- fakes ------------------------------------------------------------------


class FakeAuth:
    def __init__(self, configured: bool, tokens: dict[str, str]):
        self.is_configured = configured
        self._tokens = tokens

    def get_username_for_token(self, token):
        return self._tokens.get(token)


class FakeHandler:
    """A research handler whose ``get_status`` walks a scripted sequence of
    return values (each a dict as the real handler returns, or ``None`` for an
    unknown session). ``_active_tasks`` backs the real ``research_owns`` +
    terminal-error lookup."""

    def __init__(self, statuses, active_tasks=None):
        self._statuses = list(statuses)
        self._i = 0
        self._active_tasks = active_tasks if active_tasks is not None else {}

    def get_status(self, session_id):
        if not self._statuses:
            return None
        if self._i < len(self._statuses):
            s = self._statuses[self._i]
            self._i += 1
        else:
            s = self._statuses[-1]
        return s


def _make_app(handler, *, configured=True, tokens=None) -> FastAPI:
    app = FastAPI()
    app.state.auth_manager = FakeAuth(configured, tokens or {})
    app.include_router(setup_research_ws_routes(handler))
    return app


def _cookie(token: str) -> dict:
    return {"cookie": f"applicant_session={token}"}


@pytest.fixture(autouse=True)
def _own_everything_and_no_sleep(monkeypatch):
    """Default: the authenticated user owns the session (ownership has its own
    dedicated test below; here we isolate the transport). Also no-op the 1.5s
    inter-poll sleep so a scripted running→terminal sequence runs instantly."""
    monkeypatch.setattr(research_ws_routes, "research_owns", lambda h, sid, user: True)

    async def _no_sleep(_secs):
        return None

    monkeypatch.setattr(research_stream.asyncio, "sleep", _no_sleep)
    yield


def _drain(ws):
    """Collect (seq, data) event tuples until the terminal ``end`` frame."""
    events = []
    while True:
        m = ws.receive_json()
        if m["type"] == "end":
            return events, m
        assert m["type"] == "event"
        events.append((m["seq"], m["data"]))


# --- auth on upgrade --------------------------------------------------------


def test_unauthenticated_upgrade_is_rejected():
    app = _make_app(FakeHandler([]), configured=True, tokens={})
    with TestClient(app) as c:
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect("/api/research/ws"):
                pass  # server closes the handshake before accept


def test_foreign_owned_session_is_refused(monkeypatch):
    # Bob is authenticated but does NOT own this session.
    app = _make_app(FakeHandler([{"status": "running", "progress": {}}]),
                    configured=True, tokens={"tok": "bob"})
    monkeypatch.setattr(research_ws_routes, "research_owns", lambda h, sid, user: False)
    with TestClient(app) as c:
        with c.websocket_connect("/api/research/ws", headers=_cookie("tok")) as ws:
            ws.send_json({"type": "subscribe", "session": "rp-1"})
            msg = ws.receive_json()
            assert msg["type"] == "error"
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()


def test_real_owner_scope_refuses_a_foreign_in_memory_task(monkeypatch):
    # Use the REAL research_owns against a stamped in-memory task owner.
    monkeypatch.setattr(research_ws_routes, "research_owns", research_stream.research_owns)
    handler = FakeHandler(
        [{"status": "running", "progress": {}}],
        active_tasks={"rp-1": {"owner": "alice"}},
    )
    app = _make_app(handler, configured=True, tokens={"tok": "mallory"})
    with TestClient(app) as c:
        with c.websocket_connect("/api/research/ws", headers=_cookie("tok")) as ws:
            ws.send_json({"type": "subscribe", "session": "rp-1"})
            msg = ws.receive_json()
            assert msg["type"] == "error"


def test_real_owner_scope_admits_the_owner(monkeypatch):
    monkeypatch.setattr(research_ws_routes, "research_owns", research_stream.research_owns)
    handler = FakeHandler(
        [{"status": "done", "progress": {"phase": "writing"}}],
        active_tasks={"rp-1": {"owner": "alice"}},
    )
    app = _make_app(handler, configured=True, tokens={"tok": "alice"})
    with TestClient(app) as c:
        with c.websocket_connect("/api/research/ws", headers=_cookie("tok")) as ws:
            ws.send_json({"type": "subscribe", "session": "rp-1"})
            events, _ = _drain(ws)
            # progress snapshot then the terminal final payload.
            assert events[0][1]["status"] == "done"
            assert events[-1][1] == {"status": "done", "final": True}


# --- stream relay (SSE parity) ----------------------------------------------


def test_owner_receives_progress_then_terminal_then_end():
    handler = FakeHandler([
        {"status": "running", "progress": {"phase": "searching", "queries": 2}},
        {"status": "running", "progress": {"phase": "reading", "total_sources": 5}},
        {"status": "done", "progress": {"phase": "writing"}},
    ])
    app = _make_app(handler, configured=True, tokens={"tok": "alice"})
    with TestClient(app) as c:
        with c.websocket_connect("/api/research/ws", headers=_cookie("tok")) as ws:
            ws.send_json({"type": "subscribe", "session": "rp-1"})
            events, end = _drain(ws)
    datas = [d for _seq, d in events]
    # Progress snapshots (each carries status:running), then the terminal final.
    assert datas[0] == {"phase": "searching", "queries": 2, "status": "running"}
    assert datas[1] == {"phase": "reading", "total_sources": 5, "status": "running"}
    assert datas[2] == {"phase": "writing", "status": "done"}
    assert datas[3] == {"status": "done", "final": True}
    # seq is the monotonic per-connection index; end seq == number of events.
    assert [s for s, _ in events] == [0, 1, 2, 3]
    assert end["seq"] == 4


def test_unknown_session_yields_not_found_then_end_for_fallback():
    # get_status → None (unknown/gone session): a single not_found event + end.
    # The FE finishes the job as error and can fall back / reload — never hangs.
    app = _make_app(FakeHandler([None]), configured=True, tokens={"tok": "alice"})
    with TestClient(app) as c:
        with c.websocket_connect("/api/research/ws", headers=_cookie("tok")) as ws:
            ws.send_json({"type": "subscribe", "session": "ghost"})
            events, end = _drain(ws)
    assert events == [(0, {"status": "not_found"})]
    assert end["seq"] == 1


def test_terminal_error_carries_the_message():
    handler = FakeHandler(
        [{"status": "error", "progress": {}}],
        active_tasks={"rp-1": {"result": "boom: model unreachable"}},
    )
    app = _make_app(handler, configured=True, tokens={"tok": "alice"})
    with TestClient(app) as c:
        with c.websocket_connect("/api/research/ws", headers=_cookie("tok")) as ws:
            ws.send_json({"type": "subscribe", "session": "rp-1"})
            events, _ = _drain(ws)
    final = events[-1][1]
    assert final["status"] == "error"
    assert final["final"] is True
    assert "boom" in final["error"]


# --- reconnect resume (skip already-delivered seqs) -------------------------


def test_resume_offset_skips_already_delivered_events():
    # A reconnecting client that already saw the first 2 events resumes at
    # offset 2 — it receives ONLY events[2:] (seqs 2 and 3).
    handler = FakeHandler([
        {"status": "running", "progress": {"phase": "searching"}},
        {"status": "running", "progress": {"phase": "reading"}},
        {"status": "done", "progress": {"phase": "writing"}},
    ])
    app = _make_app(handler, configured=True, tokens={"tok": "alice"})
    with TestClient(app) as c:
        with c.websocket_connect("/api/research/ws", headers=_cookie("tok")) as ws:
            ws.send_json({"type": "subscribe", "session": "rp-1", "resume": 2})
            events, end = _drain(ws)
    assert [s for s, _ in events] == [2, 3]
    assert events[0][1] == {"phase": "writing", "status": "done"}
    assert events[1][1] == {"status": "done", "final": True}


# --- bad first frame --------------------------------------------------------


def test_non_subscribe_first_frame_is_rejected():
    app = _make_app(FakeHandler([]), configured=True, tokens={"tok": "alice"})
    with TestClient(app) as c:
        with c.websocket_connect("/api/research/ws", headers=_cookie("tok")) as ws:
            ws.send_json({"type": "hello"})
            m = ws.receive_json()
            assert m["type"] == "error"


def test_missing_session_id_is_rejected():
    app = _make_app(FakeHandler([]), configured=True, tokens={"tok": "alice"})
    with TestClient(app) as c:
        with c.websocket_connect("/api/research/ws", headers=_cookie("tok")) as ws:
            ws.send_json({"type": "subscribe", "session": ""})
            m = ws.receive_json()
            assert m["type"] == "error"
