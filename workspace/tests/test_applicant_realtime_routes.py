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
        # Every frame the workspace forwards upstream (any channel) — used to prove
        # the bridge forwards agent co-steer frames to the engine unchanged.
        self.received: list[dict] = []

    async def send(self, frame):
        self.received.append(frame)
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

    def push_down(self, chan, mtype, data):
        """Simulate the engine fanning a server-originated frame down the bridge.

        Phase 2 uses this for the ``notif`` channel: the engine's notification /
        pending-action publish seam calls ``registry.publish_all`` which fans a
        ``notif`` frame down; the workspace relays it to every browser tab.
        """
        frame = {"chan": chan, "type": mtype, "seq": self._seq, "data": data}
        self._seq += 1
        self._q.put_nowait(frame)

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


# --- notif push relay over the full bridge (Phase 2) ------------------------


def _read_frame(ws, chan, mtype, *, max_frames=12):
    """Read frames until one matches ``chan``/``mtype`` (skips presence chatter)."""
    for _ in range(max_frames):
        f = ws.receive_json()
        if f.get("chan") == chan and f.get("type") == mtype:
            return f
    raise AssertionError(f"never saw {chan}/{mtype}")


def test_engine_notif_frame_relays_down_to_the_browser_tab():
    # The engine's notification/pending-action publish seam fans a `notif` frame;
    # the workspace bridge relays it to the owner's tab so the FE can refresh off
    # the push instead of the poll.
    connector = FakeConnector()
    app = _make_app(
        configured=True, tokens={"tok": "admin"}, admins={"admin"}, connector=connector
    )
    with TestClient(app) as c:
        with c.websocket_connect(
            "/api/applicant/realtime/ws?tab=t1", headers=_cookie("tok")
        ) as ws:
            _read_presence_count(ws, 1)  # bridge is up (owner session established)
            bridge = connector.bridges["admin"]
            bridge.push_down("notif", "pending", {"event": "created"})
            frame = _read_frame(ws, "notif", "pending")
            assert frame["data"] == {"event": "created"}


def test_notif_frames_replay_on_reconnect_then_go_live():
    # A `notif` frame the engine sent while a tab was briefly gone is replayed from
    # the per-channel buffer on reconnect (gap-free), not lost.
    connector = FakeConnector()
    app = _make_app(
        configured=True, tokens={"tok": "admin"}, admins={"admin"}, connector=connector
    )
    with TestClient(app) as c:
        with c.websocket_connect(
            "/api/applicant/realtime/ws?tab=anchor", headers=_cookie("tok")
        ) as anchor:
            _read_presence_count(anchor, 1)
            bridge = connector.bridges["admin"]
            bridge.push_down("notif", "notification", {"urgency": "normal"})
            # A fresh tab (no resume hint) replays the buffered notif history.
            with c.websocket_connect(
                "/api/applicant/realtime/ws?tab=t2", headers=_cookie("tok")
            ) as t2:
                frame = _read_frame(t2, "notif", "notification")
                assert frame["data"] == {"urgency": "normal"}


# --- agent co-steer relay + forward over the full bridge (Phase 3) ----------


def test_engine_agent_event_relays_down_to_the_browser_tab():
    # The engine's agent-run publish seam fans an `agent` event; the workspace bridge
    # relays it to the owner's tab so the FE live-renders the running agent's progress.
    connector = FakeConnector()
    app = _make_app(
        configured=True, tokens={"tok": "admin"}, admins={"admin"}, connector=connector
    )
    with TestClient(app) as c:
        with c.websocket_connect(
            "/api/applicant/realtime/ws?tab=t1", headers=_cookie("tok")
        ) as ws:
            _read_presence_count(ws, 1)  # bridge is up
            bridge = connector.bridges["admin"]
            bridge.push_down("agent", "event", {"campaign_id": "c-1", "intent": "Tailoring."})
            frame = _read_frame(ws, "agent", "event")
            assert frame["data"] == {"campaign_id": "c-1", "intent": "Tailoring."}


def test_browser_agent_pause_is_forwarded_upstream_to_the_engine():
    # The workspace is thin transport: a browser agent/pause frame is forwarded to
    # the engine unchanged (the engine authorizes it). The workspace never authorizes.
    connector = FakeConnector()
    app = _make_app(
        configured=True, tokens={"tok": "admin"}, admins={"admin"}, connector=connector
    )
    with TestClient(app) as c:
        with c.websocket_connect(
            "/api/applicant/realtime/ws?tab=t1", headers=_cookie("tok")
        ) as ws:
            _read_presence_count(ws, 1)
            ws.send_json({"chan": "agent", "type": "pause", "seq": 0, "data": {"campaign_id": "c-1"}})
            # The workspace receive loop forwards frames in order on one task, so a
            # follow-up presence join whose state echo we read back guarantees the
            # earlier agent/pause was already forwarded upstream.
            ws.send_json({"chan": "presence", "type": "join", "seq": 0, "data": {"tab": "t2"}})
            _read_presence_count(ws, 2)
            bridge = connector.bridges["admin"]
            agent_frames = [f for f in bridge.received if f.get("chan") == "agent"]
            assert agent_frames, "agent/pause was never forwarded upstream"
            assert agent_frames[0]["type"] == "pause"
            assert agent_frames[0]["data"] == {"campaign_id": "c-1"}


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


# --- same-tab reconnect refcount (Greptile P1 regression) --------------------


class _RecordingBridge:
    """Captures every frame the session forwards upstream."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send(self, frame):
        self.sent.append(frame)


def _presence_types(bridge):
    return [f["type"] for f in bridge.sent if f.get("chan") == "presence"]


async def test_same_tab_reconnect_refcounts_and_suppresses_false_leave():
    """A same-tab reconnect that races the stale socket's teardown must NOT emit
    a spurious presence/leave: the tab is refcounted, so only the last socket for
    a tab announces leave, and only the first announces join."""
    from src.applicant_realtime import RealtimeBridgeSession

    session = RealtimeBridgeSession("owner", FakeConnector())
    bridge = _RecordingBridge()
    session._bridge = bridge

    # Two sockets for the SAME tab open (a reconnect overlapping the old one).
    await session.add_tab("t1")   # 0 -> 1: join
    await session.add_tab("t1")   # 1 -> 2: refcount bump, no second join
    assert _presence_types(bridge) == ["join"]
    assert session.tabs["t1"] == 2

    # The stale socket's teardown fires — the replacement is still open, so
    # NO leave is sent and the tab is still present.
    await session.remove_tab("t1")  # 2 -> 1: no leave
    assert _presence_types(bridge) == ["join"]
    assert session.tabs["t1"] == 1

    # The last socket for the tab closes — now leave is announced and the tab
    # is dropped from the registry.
    await session.remove_tab("t1")  # 1 -> 0: leave
    assert _presence_types(bridge) == ["join", "leave"]
    assert "t1" not in session.tabs
