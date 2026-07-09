"""Front-door realtime bridge: browser ⇄ workspace ⇄ engine (Phase 1 backbone).

The public surface is the workspace; the engine is internal. This module is the
workspace half of the bidirectional, per-session-multiplexed WebSocket bridge:

* a **session registry** keyed by owner (single-tenant engine → one session per
  owner) where **many tabs attach to the SAME session** (1 session : N sockets),
  each with a per-channel replay buffer so a reconnecting tab replays-then-lives;
* a single **engine bridge** WS per session that multiplexes the ``{chan,type,seq,
  data}`` envelope both ways and auto-reconnects (re-syncing presence on connect);
* a **connector seam** (:class:`EngineConnector`) so the real ``websockets`` client
  is swapped for an in-process fake in tests.

Lifted from ``workspace/src/agent_runs.py`` (buffer + subscriber-set + reconnect
replay); generalized to per-channel and given the engine bridge on top. Safety
lives at the engine (every upstream command is default-denied there); the
workspace is thin transport and only validates envelope shape.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Optional, Protocol

logger = logging.getLogger(__name__)

# --- envelope (a small local copy; the engine holds the authoritative rules) ---

FEATURE_CHANNELS = frozenset({"presence", "notif", "agent", "takeover", "chat"})
CONTROL_CHANNEL = "sys"
_ALL_CHANNELS = FEATURE_CHANNELS | {CONTROL_CHANNEL}


def parse_frame(raw: Any) -> dict[str, Any]:
    """Validate + normalize a wire object into an envelope dict.

    Raises :class:`ValueError` on a malformed frame so the caller can reject it
    without mutating state (mirrors the engine's ``parse_frame``).
    """
    if not isinstance(raw, dict):
        raise ValueError("frame must be a JSON object")
    chan = raw.get("chan")
    if not isinstance(chan, str) or chan not in _ALL_CHANNELS:
        raise ValueError(f"unknown channel: {chan!r}")
    mtype = raw.get("type")
    if not isinstance(mtype, str) or not mtype:
        raise ValueError("frame type must be a non-empty string")
    seq = raw.get("seq", 0)
    if isinstance(seq, bool) or not isinstance(seq, int):
        raise ValueError("frame seq must be an integer")
    data = raw.get("data", {})
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ValueError("frame data must be an object")
    return {"chan": chan, "type": mtype, "seq": seq, "data": data}


def control_frame(mtype: str, data: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """A point-to-point ``sys`` control frame (seq -1: excluded from replay)."""
    return {"chan": CONTROL_CHANNEL, "type": mtype, "seq": -1, "data": data or {}}


# --- engine bridge connector seam ------------------------------------------


class BridgeClosed(Exception):
    """Raised by a :class:`BridgeConn` when the engine socket has closed."""


class BridgeConn(Protocol):
    async def send(self, frame: dict[str, Any]) -> None: ...
    async def recv(self) -> dict[str, Any]: ...
    async def close(self) -> None: ...


class EngineConnector(Protocol):
    async def connect(self, session_id: str, resume: dict[str, int]) -> BridgeConn: ...


def engine_ws_base_url() -> str:
    """Derive the engine WS base from ``ENGINE_URL`` (http→ws, https→wss)."""
    base = (os.getenv("ENGINE_URL") or "http://api:8000").rstrip("/")
    if base.startswith("https://"):
        return "wss://" + base[len("https://") :]
    if base.startswith("http://"):
        return "ws://" + base[len("http://") :]
    return base


class _WebsocketsBridgeConn:
    """A :class:`BridgeConn` over a live ``websockets`` client connection."""

    def __init__(self, ws: Any) -> None:
        self._ws = ws

    async def send(self, frame: dict[str, Any]) -> None:
        await self._ws.send(json.dumps(frame))

    async def recv(self) -> dict[str, Any]:
        try:
            msg = await self._ws.recv()
        except Exception as exc:  # ConnectionClosed and friends
            raise BridgeClosed(str(exc)) from exc
        try:
            return json.loads(msg)
        except (ValueError, TypeError):
            return {}

    async def close(self) -> None:
        try:
            await self._ws.close()
        except Exception:  # pragma: no cover - close must never raise
            pass


class WebsocketsEngineConnector:
    """Production connector: opens a real WS to the engine ``/api/realtime/ws``."""

    def __init__(self, base_url: Optional[str] = None) -> None:
        self._base = (base_url or engine_ws_base_url()).rstrip("/")

    async def connect(self, session_id: str, resume: dict[str, int]) -> BridgeConn:
        import websockets  # local import: only the real path needs the dep

        url = f"{self._base}/api/realtime/ws?session={session_id}"
        if resume:
            url += "&resume=" + ",".join(f"{c}:{s}" for c, s in resume.items())
        ws = await websockets.connect(url)
        return _WebsocketsBridgeConn(ws)


# --- per-owner session (N browser sockets ⇄ one engine bridge) --------------

_RECONNECT_BASE_S = 0.5
_RECONNECT_MAX_S = 8.0
_RECONNECT_ATTEMPTS = 6


class RealtimeBridgeSession:
    """One owner's session: browser subscribers + per-channel replay + engine bridge."""

    def __init__(self, session_id: str, connector: EngineConnector) -> None:
        self.session_id = session_id
        self._connector = connector
        self.channels: dict[str, list[dict[str, Any]]] = {}
        self.subscribers: set[asyncio.Queue] = set()
        self.tabs: set[str] = set()
        self._bridge: Optional[BridgeConn] = None
        self._bridge_task: Optional[asyncio.Task] = None
        self._closed = False
        self._degraded_sent = False

    # -- browser-facing fan-out (relay preserves the engine's seq) ----------

    def relay(self, frame: dict[str, Any]) -> None:
        """Append an engine-originated frame (preserving its seq) and fan it out."""
        chan = frame.get("chan", "")
        if chan in FEATURE_CHANNELS and isinstance(frame.get("seq"), int) and frame["seq"] >= 0:
            self.channels.setdefault(chan, []).append(frame)
        for q in list(self.subscribers):
            try:
                q.put_nowait(frame)
            except Exception:  # pragma: no cover
                pass

    def attach(self, resume: Optional[dict[str, int]] = None) -> asyncio.Queue:
        """Register a browser subscriber and replay each channel's buffered tail."""
        q: asyncio.Queue = asyncio.Queue()
        self.subscribers.add(q)
        resume = resume or {}
        for chan, buf in self.channels.items():
            last = resume.get(chan, -1)
            for frame in buf:
                if frame.get("seq", -1) > last:
                    q.put_nowait(frame)
        return q

    def detach(self, q: asyncio.Queue) -> None:
        self.subscribers.discard(q)

    def _resume_map(self) -> dict[str, int]:
        """Highest seq seen per channel — the resume hint for a bridge reconnect."""
        out: dict[str, int] = {}
        for chan, buf in self.channels.items():
            if buf:
                out[chan] = buf[-1].get("seq", -1)
        return out

    # -- engine bridge lifecycle -------------------------------------------

    def ensure_bridge(self) -> None:
        """Start the background engine-bridge loop once (idempotent)."""
        if self._bridge_task is None or self._bridge_task.done():
            self._closed = False
            self._bridge_task = asyncio.create_task(self._bridge_loop())

    async def _bridge_loop(self) -> None:
        backoff = _RECONNECT_BASE_S
        attempts = 0
        while not self._closed:
            try:
                conn = await self._connector.connect(self.session_id, self._resume_map())
            except Exception as exc:
                attempts += 1
                logger.info("realtime bridge connect failed (%s): %s", attempts, exc)
                if attempts >= _RECONNECT_ATTEMPTS:
                    self._emit_degraded()
                    return
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _RECONNECT_MAX_S)
                continue
            self._bridge = conn
            self._degraded_sent = False
            backoff = _RECONNECT_BASE_S
            attempts = 0
            # Re-sync presence so the engine's count matches the tabs we hold now.
            await self._safe_send(
                {"chan": "presence", "type": "sync", "seq": 0, "data": {"members": sorted(self.tabs)}}
            )
            try:
                while not self._closed:
                    frame = await conn.recv()
                    if frame:
                        self.relay(frame)
            except BridgeClosed:
                self._bridge = None
                if self._closed:
                    return
                # fall through to reconnect
            except Exception:  # pragma: no cover - defensive
                self._bridge = None
            await asyncio.sleep(backoff)

    def _emit_degraded(self) -> None:
        """Tell every tab the push channel is unavailable so the FE can fall back."""
        if self._degraded_sent:
            return
        self._degraded_sent = True
        for q in list(self.subscribers):
            try:
                q.put_nowait(control_frame("degraded", {"reason": "engine bridge unavailable"}))
            except Exception:  # pragma: no cover
                pass

    async def _safe_send(self, frame: dict[str, Any]) -> None:
        conn = self._bridge
        if conn is None:
            return
        try:
            await conn.send(frame)
        except Exception:
            self._bridge = None  # reader loop will notice + reconnect

    async def send_upstream(self, frame: dict[str, Any]) -> None:
        """Forward a browser frame to the engine (engine authorizes it, not us)."""
        await self._safe_send(frame)

    async def add_tab(self, tab: str) -> None:
        self.tabs.add(tab)
        await self._safe_send({"chan": "presence", "type": "join", "seq": 0, "data": {"tab": tab}})

    async def remove_tab(self, tab: str) -> None:
        self.tabs.discard(tab)
        await self._safe_send({"chan": "presence", "type": "leave", "seq": 0, "data": {"tab": tab}})

    async def shutdown(self) -> None:
        self._closed = True
        if self._bridge_task and not self._bridge_task.done():
            self._bridge_task.cancel()
        if self._bridge is not None:
            await self._bridge.close()
            self._bridge = None


class RealtimeHub:
    """Process-lived registry of owner sessions, sharing one engine bridge each."""

    def __init__(self, connector: Optional[EngineConnector] = None) -> None:
        self.connector: EngineConnector = connector or WebsocketsEngineConnector()
        self._sessions: dict[str, RealtimeBridgeSession] = {}

    def get_or_create(self, session_id: str) -> RealtimeBridgeSession:
        sess = self._sessions.get(session_id)
        if sess is None:
            sess = RealtimeBridgeSession(session_id, self.connector)
            self._sessions[session_id] = sess
        return sess

    def get(self, session_id: str) -> Optional[RealtimeBridgeSession]:
        return self._sessions.get(session_id)

    async def release(self, session_id: str) -> None:
        """Tear a session down once its last tab has left (frees the engine bridge)."""
        sess = self._sessions.get(session_id)
        if sess is None or sess.subscribers:
            return
        self._sessions.pop(session_id, None)
        await sess.shutdown()


def get_hub(app: Any) -> RealtimeHub:
    """The one hub per workspace process, stored on ``app.state`` (test-overridable)."""
    hub = getattr(app.state, "applicant_realtime_hub", None)
    if hub is None:
        hub = RealtimeHub()
        app.state.applicant_realtime_hub = hub
    return hub


# --- WebSocket upgrade auth (owner-scoped, mirrors require_engine_owner) ----

_PROXY_FWD_HEADERS = (
    "cf-connecting-ip", "cf-ray", "cf-visitor",
    "x-forwarded-for", "x-forwarded-host", "x-real-ip", "forwarded",
)
SESSION_COOKIE = "applicant_session"


def _ws_is_trusted_loopback(ws: Any) -> bool:
    client = getattr(ws, "client", None)
    host = (getattr(client, "host", "") if client else "") or ""
    if host not in ("127.0.0.1", "::1", "localhost"):
        return False
    headers = getattr(ws, "headers", None) or {}
    for h in _PROXY_FWD_HEADERS:
        try:
            if headers.get(h):
                return False
        except Exception:  # pragma: no cover
            return False
    return True


def resolve_ws_owner(ws: Any) -> tuple[bool, Optional[str]]:
    """Authenticate a WS upgrade by the ``applicant_session`` cookie, owner-scoped.

    Mirrors ``src.auth_helpers.require_engine_owner`` (the engine is single-tenant,
    so any second account must be rejected) but for the WebSocket handshake, which
    the ``BaseHTTPMiddleware`` auth gate never runs for. Returns ``(ok, owner)``;
    ``ok`` is False for an unauthenticated or non-owner upgrade so the caller can
    close the handshake BEFORE accepting (no channel opens).
    """
    app = getattr(ws, "app", None)
    auth_mgr = getattr(getattr(app, "state", None), "auth_manager", None)
    configured = bool(getattr(auth_mgr, "is_configured", False)) if auth_mgr else False

    token = None
    try:
        token = ws.cookies.get(SESSION_COOKIE)
    except Exception:  # pragma: no cover
        token = None
    username = None
    if auth_mgr is not None and token:
        try:
            username = auth_mgr.get_username_for_token(token)
        except Exception:
            username = None

    if not configured:
        # First-run / single-user: a logged-in owner passes; otherwise only a
        # DIRECT loopback caller (no proxy-forward headers) is trusted.
        if username:
            return True, username
        if _ws_is_trusted_loopback(ws):
            return True, ""
        return False, None

    if not username:
        return False, None
    # Configured for multiple accounts: only the admin (the engine owner) attaches.
    try:
        if bool(auth_mgr.is_admin(username)):
            return True, username
    except Exception:
        return False, None
    return False, None
