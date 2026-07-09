"""Hermetic tests for the front-door realtime WebSocket bridge (Phase 1 backbone).

Mounts only ``routes/applicant_realtime_routes.py`` on a bare FastAPI app with a
fake ``auth_manager`` on ``app.state`` (the real global gate + AuthMiddleware are
out of scope and never run for WebSocket scopes anyway) and an injected FAKE
engine connector so the bridge round-trips in-process with zero network.

Covers the spec's Phase-1 test contract: auth-rejects-unauthenticated /
non-owner upgrade; owner-scope (a second account can't attach); envelope
round-trip + presence join/leave/count over the full bridge; reconnect replays
the buffer then goes live; dropping one subscriber doesn't kill the session or
the other tab.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from routes.applicant_realtime_routes import setup_applicant_realtime_routes
from src.applicant_realtime import BridgeClosed, RealtimeHub


# --- fakes ------------------------------------------------------------------


class FakeAuth:
    def __init__(self, configured: bool, tokens: dict[str, str], admins: set[str]):
        self.is_configured = configured
        self._tokens = tokens
        self._admins = admins

    def get_username_for_token(self, token):
        return self._tokens.get(token)

    def is_admin(self, user):
        return user in self._admins


class FakeEngineBridge:
    """Stands in for the engine's realtime session over the bridge WS.

    Mirrors the engine's presence semantics: join/leave/sync mutate a member set
    and it emits a monotonic ``presence/state`` frame downstream — proving the
    workspace forwards upstream and fans the echo down to every tab.
    """

    def __init__(self) -> None:
        self._members: set[str] = set()
        self._seq = 0
        self._q: asyncio.Queue = asyncio.Queue()
        self._closed = False

    async def send(self, frame):
        if frame.get("chan") != "presence":
            return
        t = frame.get("type")
        data = frame.get("data") or {}
        if t == "join":
            self._members.add(str(data.get("tab", "")))
        elif t == "leave":
            self._members.discard(str(data.get("tab", "")))
        elif t == "sync":
            self._members = {str(m) for m in data.get("members", [])}
        self._members.discard("")
        self._emit_state()

    def _emit_state(self):
        self._q.put_nowait(
            {
                "chan": "presence",
                "type": "state",
                "seq": self._seq,
                "data": {"count": len(self._members), "members": sorted(self._members)},
            }
        )
        self._seq += 1

    async def recv(self):
        frame = await self._q.get()
        if frame is None:
            raise BridgeClosed("closed")
        return frame

    async def close(self):
        self._closed = True
        self._q.put_nowait(None)


class FakeConnector:
    def __init__(self) -> None:
        self.bridges: dict[str, FakeEngineBridge] = {}

    async def connect(self, session_id, resume):
        bridge = FakeEngineBridge()
        self.bridges[session_id] = bridge
        return bridge


# --- app builder ------------------------------------------------------------


def _make_app(*, configured=True, tokens=None, admins=None, connector=None) -> FastAPI:
    app = FastAPI()
    app.state.auth_manager = FakeAuth(configured, tokens or {}, admins or set())
    app.state.applicant_realtime_hub = RealtimeHub(connector=connector or FakeConnector())
    app.include_router(setup_applicant_realtime_routes())
    return app


def _cookie(token: str) -> dict:
    return {"cookie": f"applicant_session={token}"}


def _read_presence_count(ws, expected, *, max_frames=12):
    """Read frames until a ``presence/state`` reports ``expected`` count."""
    for _ in range(max_frames):
        f = ws.receive_json()
        if f["chan"] == "presence" and f["type"] == "state" and f["data"]["count"] == expected:
            return f
    raise AssertionError(f"never saw presence count {expected}")


# --- auth on upgrade --------------------------------------------------------


def test_unauthenticated_upgrade_is_rejected():
    app = _make_app(configured=True, tokens={}, admins=set())
    with TestClient(app) as c:
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect("/api/applicant/realtime/ws"):
                pass  # server closes the handshake before accept


def test_non_owner_second_account_cannot_attach():
    # Configured for multiple accounts: only the admin (engine owner) may attach.
    app = _make_app(configured=True, tokens={"bob": "bob"}, admins={"admin"})
    with TestClient(app) as c:
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect("/api/applicant/realtime/ws", headers=_cookie("bob")):
                pass


def test_owner_upgrade_is_accepted_and_greeted():
    app = _make_app(configured=True, tokens={"tok": "admin"}, admins={"admin"})
    with TestClient(app) as c:
        with c.websocket_connect("/api/applicant/realtime/ws", headers=_cookie("tok")) as ws:
            hello = ws.receive_json()
            assert hello["chan"] == "sys"
            assert hello["type"] == "hello"


# --- presence round-trip over the full bridge -------------------------------


def test_presence_round_trip_join_and_count():
    app = _make_app(configured=True, tokens={"tok": "admin"}, admins={"admin"})
    with TestClient(app) as c:
        with c.websocket_connect(
            "/api/applicant/realtime/ws?tab=t1", headers=_cookie("tok")
        ) as ws:
            # The workspace forwarded our join upstream; the engine echo comes back down.
            _read_presence_count(ws, 1)


def test_two_tabs_share_one_session_and_see_the_same_count():
    app = _make_app(configured=True, tokens={"tok": "admin"}, admins={"admin"})
    with TestClient(app) as c:
        with c.websocket_connect(
            "/api/applicant/realtime/ws?tab=t1", headers=_cookie("tok")
        ) as a:
            _read_presence_count(a, 1)
            with c.websocket_connect(
                "/api/applicant/realtime/ws?tab=t2", headers=_cookie("tok")
            ) as b:
                # Both tabs of the one owner observe the count rise to 2 (co-driving).
                _read_presence_count(b, 2)
                _read_presence_count(a, 2)


def test_dropping_one_tab_keeps_the_session_and_updates_the_other():
    app = _make_app(configured=True, tokens={"tok": "admin"}, admins={"admin"})
    with TestClient(app) as c:
        with c.websocket_connect(
            "/api/applicant/realtime/ws?tab=t1", headers=_cookie("tok")
        ) as a:
            _read_presence_count(a, 1)
            with c.websocket_connect(
                "/api/applicant/realtime/ws?tab=t2", headers=_cookie("tok")
            ) as b:
                _read_presence_count(b, 2)
                _read_presence_count(a, 2)
            # b closed → the surviving tab a sees the count fall back to 1, and the
            # session (and its bridge) is still alive for a.
            _read_presence_count(a, 1)


def test_reconnect_replays_the_buffer_then_goes_live():
    app = _make_app(configured=True, tokens={"tok": "admin"}, admins={"admin"})
    with TestClient(app) as c:
        # An anchor tab keeps the session (and its per-channel buffer) alive across
        # the reconnecting tab's disconnect.
        with c.websocket_connect(
            "/api/applicant/realtime/ws?tab=anchor", headers=_cookie("tok")
        ) as anchor:
            _read_presence_count(anchor, 1)
            with c.websocket_connect(
                "/api/applicant/realtime/ws?tab=t1", headers=_cookie("tok")
            ) as t:
                _read_presence_count(t, 2)
            _read_presence_count(anchor, 1)  # t left
            # Reconnect a fresh socket with NO resume: it replays the session's
            # buffered presence history before any new live frame.
            with c.websocket_connect(
                "/api/applicant/realtime/ws?tab=t1b", headers=_cookie("tok")
            ) as t2:
                first = None
                for _ in range(12):
                    f = t2.receive_json()
                    if f["chan"] == "presence" and f["type"] == "state":
                        first = f
                        break
                assert first is not None, "no replayed presence state on reconnect"
                # then it also goes live up to the current count (anchor + t1b = 2)
                _read_presence_count(t2, 2)
