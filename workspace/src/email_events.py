"""Owner-scoped email-events relay (workspace-native WebSocket push).

This is the workspace half of the **IMAP-IDLE → browser** relay that lets the
inbox's new-mail signal retire its 60s unread-count poll to a *fallback* lane.

Why a NEW channel (not the applicant realtime bridge): ``/api/applicant/realtime/
ws`` (``src/applicant_realtime.py``) carries the ENGINE's job-search notifications,
not workspace email — gating the email poll on that channel would suppress it while
no email events ever arrive there (a silent dead inbox). This module is a small,
workspace-native fan-out registry that a background IMAP-IDLE watcher
(``src/email_idle_watcher.py``) publishes into, keyed by OWNER.

Design (lifted from ``RealtimeBridgeSession``'s subscriber-set + fan-out, stripped
of the engine bridge):

* an :class:`EmailEventsHub` process-lived registry keyed by owner — ``publish`` fans
  a frame ONLY to that owner's subscribers, so an owner can never receive another
  owner's mail signal;
* per-owner **liveness**: an owner is "live" only while at least one of their IMAP
  accounts has an established IDLE watcher. The watcher toggles liveness; the hub
  emits a ``live``/``down`` frame on any transition and a periodic ``live``
  heartbeat, and reports the current level to a freshly-attached socket. The FE
  suppresses its poll ONLY while it is actively receiving that live signal — every
  other state (no socket, no heartbeat, an account whose server has no IDLE, an
  auth/connect failure) keeps the poll running. No silent dead UI.

Envelope: a small ``{"type": ..., "data": {...}}`` object (the relay is one-way
server→browser; there is no upstream verb, so it needs no seq/replay machinery).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

# Reuse the exact loopback-trust + cookie-name helpers the other workspace WS
# routes use, so this handshake auth matches them byte-for-byte.
from src.applicant_realtime import _ws_is_trusted_loopback, SESSION_COOKIE

logger = logging.getLogger(__name__)


def _norm_owner(owner: Optional[str]) -> str:
    """Normalize a nullable owner to the canonical key ("" for the null bucket)."""
    return owner or ""


# --- frames -----------------------------------------------------------------


def hello_frame(owner: str) -> dict[str, Any]:
    """First frame on connect (carries no liveness — a live/down frame follows)."""
    return {"type": "hello", "data": {"owner": owner}}


def live_frame(live: bool) -> dict[str, Any]:
    """Liveness signal + heartbeat. ``live`` true ⇒ the FE may suppress its poll."""
    return {"type": "live" if live else "down", "data": {"live": bool(live)}}


def unread_changed_frame(account_id: str) -> dict[str, Any]:
    """New inbound mail was detected for one account — the FE re-hits the unread
    endpoint (a nudge; it carries no message content and adds no authority)."""
    return {"type": "email:unread-changed", "data": {"account_id": account_id}}


# --- hub --------------------------------------------------------------------


class EmailEventsHub:
    """Process-lived, owner-scoped fan-out registry for email push frames."""

    def __init__(self) -> None:
        # owner -> set of browser subscriber queues
        self._subs: dict[str, set[asyncio.Queue]] = {}
        # owner -> set of account_ids currently pushing live (IDLE established)
        self._live_accounts: dict[str, set[str]] = {}
        # owner -> set of account_ids the watcher manager EXPECTS to cover (every
        # enabled account, IDLE-capable or not). This is the denominator: an owner
        # is only poll-suppressible when EVERY expected account is live, so an
        # account whose server lacks IDLE (or whose watcher failed) — which stays
        # enumerated but never live — keeps the poll on for the whole owner.
        self._expected_accounts: dict[str, set[str]] = {}

    # -- browser subscribers --------------------------------------------------

    def attach(self, owner: Optional[str]) -> asyncio.Queue:
        """Register a browser subscriber for ``owner`` and return its queue."""
        key = _norm_owner(owner)
        q: asyncio.Queue = asyncio.Queue()
        self._subs.setdefault(key, set()).add(q)
        return q

    def detach(self, owner: Optional[str], q: asyncio.Queue) -> None:
        key = _norm_owner(owner)
        subs = self._subs.get(key)
        if subs is not None:
            subs.discard(q)
            if not subs:
                self._subs.pop(key, None)

    def publish(self, owner: Optional[str], frame: dict[str, Any]) -> None:
        """Fan a frame out to ONLY ``owner``'s subscribers (owner isolation)."""
        key = _norm_owner(owner)
        for q in list(self._subs.get(key, ())):
            try:
                q.put_nowait(frame)
            except Exception:  # pragma: no cover - a full/closed queue must not raise
                pass

    def subscriber_count(self, owner: Optional[str]) -> int:
        return len(self._subs.get(_norm_owner(owner), ()))

    # -- liveness (driven by the IDLE watcher) --------------------------------

    def _owner_live(self, key: str) -> bool:
        """An owner is live only when EVERY expected account is currently live.

        The FE's unread poll is scoped to the *active* account, so suppressing it
        on owner-level "any account live" would starve an active account whose own
        watcher failed or whose server lacks IDLE while a *different* account keeps
        emitting live heartbeats. Requiring every enumerated account to be live
        keeps the poll on whenever any one of them cannot honestly push."""
        expected = self._expected_accounts.get(key)
        if not expected:
            return False
        live = self._live_accounts.get(key, set())
        return expected.issubset(live)

    def is_live(self, owner: Optional[str]) -> bool:
        return self._owner_live(_norm_owner(owner))

    def set_expected_accounts(
        self, owner: Optional[str], account_ids: "set[str] | list[str] | tuple[str, ...]"
    ) -> None:
        """Record the full set of accounts the watcher manager covers for ``owner``
        (the liveness denominator). Prunes any now-unexpected live account and emits
        a ``live``/``down`` frame if the owner-level liveness flips as a result."""
        key = _norm_owner(owner)
        was_live = self._owner_live(key)
        new_expected = set(account_ids)
        if new_expected:
            self._expected_accounts[key] = new_expected
        else:
            self._expected_accounts.pop(key, None)
        live = self._live_accounts.get(key)
        if live:
            live &= new_expected
            if not live:
                self._live_accounts.pop(key, None)
        if self._owner_live(key) != was_live:
            self.publish(key, live_frame(self._owner_live(key)))

    def set_account_live(self, owner: Optional[str], account_id: str, live: bool) -> None:
        """Record whether one account's IDLE watcher is established. Emits a
        ``live``/``down`` frame to the owner only when the owner-level liveness
        (every expected account live) flips as a result."""
        key = _norm_owner(owner)
        was_live = self._owner_live(key)
        cur = self._live_accounts.setdefault(key, set())
        if live:
            cur.add(account_id)
        else:
            cur.discard(account_id)
        if not cur:
            self._live_accounts.pop(key, None)
        if self._owner_live(key) != was_live:
            self.publish(key, live_frame(self._owner_live(key)))

    def heartbeat(self, owner: Optional[str] = None) -> None:
        """Re-emit current liveness so a browser can detect a stale push path.

        With no argument, heartbeats every currently-live owner. The FE arms a
        staleness timer on each ``live`` frame; if heartbeats stop arriving it
        restores its poll even while the socket stays open."""
        if owner is not None:
            owners = [_norm_owner(owner)]
        else:
            owners = list(self._expected_accounts.keys())
        for key in owners:
            if self._owner_live(key):
                self.publish(key, live_frame(True))


def get_email_events_hub(app: Any) -> EmailEventsHub:
    """The one hub per workspace process, stored on ``app.state`` (test-overridable)."""
    hub = getattr(app.state, "email_events_hub", None)
    if hub is None:
        hub = EmailEventsHub()
        app.state.email_events_hub = hub
    return hub


# --- WebSocket upgrade auth (owner-scoped, mirrors the chat-WS handshake) ----


def resolve_ws_email_user(ws: Any) -> tuple[bool, Optional[str]]:
    """Authenticate an email-events WS upgrade by the ``applicant_session`` cookie.

    Mirrors ``routes.chat_ws_routes._resolve_ws_chat_user``: any authenticated user
    passes and is scoped to their OWN owner key; the ``BaseHTTPMiddleware`` auth gate
    never runs for WebSocket scopes, which is why this authenticates the handshake
    itself. In unconfigured first-run mode only a DIRECT loopback caller (no
    proxy-forward headers) is trusted, as the empty-string owner. Returns
    ``(ok, owner)``; ``ok`` is False so the caller closes BEFORE accept (no push
    opens for an unauthenticated upgrade).
    """
    app = getattr(ws, "app", None)
    auth_mgr = getattr(getattr(app, "state", None), "auth_manager", None)
    configured = bool(getattr(auth_mgr, "is_configured", False)) if auth_mgr else False

    token = None
    try:
        token = ws.cookies.get(SESSION_COOKIE)
    except Exception:  # pragma: no cover - malformed cookie header
        token = None

    username = None
    if auth_mgr is not None and token:
        try:
            username = auth_mgr.get_username_for_token(token)
        except Exception:
            username = None

    if username:
        return True, username
    # Unconfigured / first-run: only a DIRECT loopback caller (no proxy-forward
    # headers) is trusted, as the "" owner — matching require_user's first-run path.
    if not configured and _ws_is_trusted_loopback(ws):
        return True, ""
    return False, None
