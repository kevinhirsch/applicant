"""Hermetic tests for the owner-scoped IMAP-IDLE → WebSocket email relay.

NO real network / IMAP: a FAKE idle connection (``FakeIdle``) drives the watcher
in-process, and the WS route is mounted on a bare FastAPI app with a fake
``auth_manager`` (the real global gate + AuthMiddleware never run for WebSocket
scopes anyway).

Covers the relay's contract:
  * WS auth rejects an unauthenticated upgrade; an authenticated owner is greeted
    with the current liveness level;
  * owner isolation — a new-mail signal reaches ONLY the owning owner's socket;
  * new mail detected ⇒ an ``email:unread-changed`` push to the right owner;
  * auth/connect failure and a non-IDLE server ⇒ NO live signal (the owner stays
    ``down`` so the FE keeps polling — no silent dead inbox);
  * clean shutdown stops every watcher and closes its connection (no leaks).
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from routes.email_events_ws_routes import setup_email_events_ws_routes
from src.email_idle_watcher import AccountWatcher, EmailIdleManager
from src.email_events import EmailEventsHub


# --- fakes ------------------------------------------------------------------


class FakeAuth:
    def __init__(self, configured: bool, tokens: dict[str, str]):
        self.is_configured = configured
        self._tokens = tokens

    def get_username_for_token(self, token):
        return self._tokens.get(token)


class FakeIdle:
    """Async stand-in for :class:`ImapIdleConnection` (no threads, no sockets).

    ``events`` is a script of ``wait_for_change`` results; once exhausted it returns
    ``"timeout"`` on a short cadence so the watcher stays established until stopped.
    """

    def __init__(self, *, has_idle=True, connect_error=False, events=None):
        self._has_idle = has_idle
        self._connect_error = connect_error
        self._events = list(events or [])
        self.connected = False
        self.closed = False
        self.delivered = asyncio.Event()

    async def connect(self):
        if self._connect_error:
            raise RuntimeError("auth failed")  # NB: no creds in the message
        self.connected = True

    async def has_idle(self):
        return self._has_idle

    async def select_inbox_count(self):
        return 0

    async def wait_for_change(self, stop_event):
        if self._events:
            ev = self._events.pop(0)
            if not self._events:
                self.delivered.set()
            return ev
        self.delivered.set()
        await asyncio.sleep(0.02)
        return "timeout"

    async def close(self):
        self.closed = True


async def _drain_types(q: asyncio.Queue, *, want: str, timeout: float = 2.0) -> list[str]:
    """Read frames until one of type ``want`` arrives; return the types seen."""
    seen: list[str] = []
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            raise AssertionError(f"never saw {want!r}; saw {seen}")
        frame = await asyncio.wait_for(q.get(), timeout=remaining)
        seen.append(frame.get("type"))
        if frame.get("type") == want:
            return seen


# --- watcher: new mail detected ⇒ push to the RIGHT owner only ---------------


async def test_new_mail_pushes_to_the_owning_owner_only():
    hub = EmailEventsHub()
    qa = hub.attach("alice")
    qb = hub.attach("bob")
    conn = FakeIdle(events=["new"])
    # The manager declares the expected account set (the liveness denominator)
    # before starting watchers; mirror that so this account going live marks the
    # owner live.
    hub.set_expected_accounts("alice", {"acct-a"})
    watcher = AccountWatcher("alice", "acct-a", hub, lambda o, a: conn)
    watcher.start()
    try:
        # alice sees a `live` frame (watcher established) then the new-mail nudge.
        types_seen = await _drain_types(qa, want="email:unread-changed")
        assert "live" in types_seen
        assert "email:unread-changed" in types_seen
        # bob's socket saw NOTHING — owner isolation holds.
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(qb.get(), timeout=0.15)
    finally:
        await watcher.stop()


async def test_new_mail_frame_names_the_account():
    hub = EmailEventsHub()
    q = hub.attach("alice")
    conn = FakeIdle(events=["new"])
    watcher = AccountWatcher("alice", "acct-xyz", hub, lambda o, a: conn)
    watcher.start()
    try:
        # Skip the `live` frame, capture the nudge.
        frame = None
        for _ in range(6):
            f = await asyncio.wait_for(q.get(), timeout=2.0)
            if f.get("type") == "email:unread-changed":
                frame = f
                break
        assert frame is not None
        assert frame["data"]["account_id"] == "acct-xyz"
    finally:
        await watcher.stop()


# --- auth/connect failure ⇒ NO live signal (FE keeps polling) ---------------


async def test_connect_failure_never_marks_live():
    hub = EmailEventsHub()
    q = hub.attach("alice")
    conn = FakeIdle(connect_error=True)
    watcher = AccountWatcher("alice", "acct-a", hub, lambda o, a: conn)
    watcher.start()
    try:
        await asyncio.sleep(0.1)  # let the first connect attempt fail
        # The owner was never marked live, so no `live` frame was published and the
        # FE keeps polling this account — no silent dead inbox.
        assert hub.is_live("alice") is False
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(q.get(), timeout=0.1)
    finally:
        await watcher.stop()


async def test_non_idle_server_never_marks_live():
    hub = EmailEventsHub()
    q = hub.attach("alice")
    conn = FakeIdle(has_idle=False)
    watcher = AccountWatcher("alice", "acct-a", hub, lambda o, a: conn)
    watcher.start()
    try:
        await asyncio.sleep(0.1)
        assert hub.is_live("alice") is False
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(q.get(), timeout=0.1)
        # A non-IDLE server means the watcher gives up (no reconnect loop churning).
        assert conn.connected is True
    finally:
        await watcher.stop()


# --- hub-level owner isolation ----------------------------------------------


def test_hub_publish_is_owner_scoped():
    hub = EmailEventsHub()
    qa = hub.attach("alice")
    qb = hub.attach("bob")
    hub.publish("alice", {"type": "email:unread-changed", "data": {"account_id": "x"}})
    assert qa.get_nowait()["type"] == "email:unread-changed"
    assert qb.empty()  # bob never sees alice's mail signal


def test_hub_liveness_requires_every_expected_account_live():
    hub = EmailEventsHub()
    q = hub.attach("alice")
    # Two accounts are expected (the liveness denominator). The owner is only
    # poll-suppressible once EVERY one is live — the FE's unread poll is scoped to
    # the active account, so one live account must not suppress another's fallback.
    hub.set_expected_accounts("alice", {"a1", "a2"})
    hub.set_account_live("alice", "a1", True)
    assert hub.is_live("alice") is False   # a2 not live yet ⇒ poll stays on
    assert q.empty()                       # no premature `live` frame
    hub.set_account_live("alice", "a2", True)
    assert hub.is_live("alice") is True
    assert q.get_nowait()["type"] == "live"
    assert q.empty()
    # Any account dropping flips the owner down (a single `down`).
    hub.set_account_live("alice", "a1", False)
    assert hub.is_live("alice") is False
    assert q.get_nowait()["type"] == "down"
    assert q.empty()
    hub.set_account_live("alice", "a2", False)
    assert q.empty()  # already down; no duplicate


def test_hub_unexpected_account_alone_is_not_live():
    # Regression for the per-account scoping gap: a live signal from one account
    # must NOT mark an owner live while another expected account has no watcher.
    hub = EmailEventsHub()
    hub.set_expected_accounts("alice", {"a1", "a2"})
    hub.set_account_live("alice", "a1", True)  # a2 never establishes IDLE
    assert hub.is_live("alice") is False
    # Once a2's account is removed from the expected set, a1 alone suffices.
    hub.set_expected_accounts("alice", {"a1"})
    assert hub.is_live("alice") is True


# --- manager lifecycle: clean shutdown, no leaks ----------------------------


async def test_manager_starts_watchers_and_stops_cleanly():
    hub = EmailEventsHub()
    conn = FakeIdle(events=[])  # stays established (timeouts) until stopped
    mgr = EmailIdleManager(
        hub,
        conn_factory=lambda o, a: conn,
        account_source=lambda: [("alice", "acct-a")],
    )
    await mgr.start()
    try:
        assert mgr.watcher_count == 1
        # The account establishes IDLE and goes live.
        await asyncio.wait_for(conn.delivered.wait(), timeout=2.0)
        assert hub.is_live("alice") is True
    finally:
        await mgr.stop()
    # After shutdown: no watchers, the connection was closed (no leaked socket),
    # and the owner is no longer marked live.
    assert mgr.watcher_count == 0
    assert conn.closed is True
    assert hub.is_live("alice") is False


async def test_manager_refresh_drops_removed_accounts():
    hub = EmailEventsHub()
    conns: dict[str, FakeIdle] = {}

    def factory(owner, account_id):
        c = FakeIdle(events=[])
        conns[account_id] = c
        return c

    accounts = [("alice", "a1"), ("bob", "b1")]
    mgr = EmailIdleManager(hub, conn_factory=factory, account_source=lambda: list(accounts))
    await mgr.start()
    try:
        assert mgr.watcher_count == 2
        # bob's account is removed; a refresh tears its watcher down.
        accounts[:] = [("alice", "a1")]
        await mgr.refresh()
        assert mgr.watcher_count == 1
        assert conns["b1"].closed is True
    finally:
        await mgr.stop()


# --- WS route: auth + owner-scoped initial liveness -------------------------


def _make_ws_app(*, configured=True, tokens=None, hub=None) -> FastAPI:
    app = FastAPI()
    app.state.auth_manager = FakeAuth(configured, tokens or {})
    app.state.email_events_hub = hub if hub is not None else EmailEventsHub()
    app.include_router(setup_email_events_ws_routes())
    return app


def _cookie(token: str) -> dict:
    return {"cookie": f"applicant_session={token}"}


def test_unauthenticated_ws_upgrade_is_rejected():
    app = _make_ws_app(configured=True, tokens={})
    with TestClient(app) as c:
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect("/api/email/events/ws"):
                pass


def test_authenticated_owner_is_greeted_with_liveness():
    app = _make_ws_app(configured=True, tokens={"tok": "alice"})
    with TestClient(app) as c:
        with c.websocket_connect("/api/email/events/ws", headers=_cookie("tok")) as ws:
            hello = ws.receive_json()
            assert hello["type"] == "hello"
            assert hello["data"]["owner"] == "alice"
            live = ws.receive_json()
            # No watcher is live in this bare app, so the FE is told `down` (keep polling).
            assert live["type"] == "down"


def test_connect_reports_current_live_level():
    hub = EmailEventsHub()
    hub.set_expected_accounts("alice", {"a1"})
    hub.set_account_live("alice", "a1", True)  # watcher already live before connect
    app = _make_ws_app(configured=True, tokens={"tok": "alice"}, hub=hub)
    with TestClient(app) as c:
        with c.websocket_connect("/api/email/events/ws", headers=_cookie("tok")) as ws:
            assert ws.receive_json()["type"] == "hello"
            # The socket that connects AFTER the watcher is live is told so immediately.
            assert ws.receive_json()["type"] == "live"


def test_two_owners_get_their_own_scoped_liveness():
    hub = EmailEventsHub()
    hub.set_expected_accounts("alice", {"a1"})
    hub.set_account_live("alice", "a1", True)  # only alice is live
    app = _make_ws_app(configured=True, tokens={"ta": "alice", "tb": "bob"}, hub=hub)
    with TestClient(app) as c:
        with c.websocket_connect("/api/email/events/ws", headers=_cookie("ta")) as wa:
            assert wa.receive_json()["data"]["owner"] == "alice"
            assert wa.receive_json()["type"] == "live"
            with c.websocket_connect("/api/email/events/ws", headers=_cookie("tb")) as wb:
                assert wb.receive_json()["data"]["owner"] == "bob"
                # bob is NOT live (only alice's account is) — bob keeps polling.
                assert wb.receive_json()["type"] == "down"
