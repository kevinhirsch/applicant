"""Background IMAP-IDLE watcher — the source of the workspace email push.

For each owner's configured, IDLE-capable IMAP account this maintains a persistent
connection that issues IMAP IDLE and detects new inbound mail (an EXISTS/RECENT
increase), then publishes an owner-scoped ``email:unread-changed`` frame into the
:class:`~src.email_events.EmailEventsHub`. That lets the front-door inbox retire its
60s unread-count poll to a fallback lane — but ONLY while the push is genuinely live
(the honesty invariant): an account whose server has no IDLE, or whose connect/login
fails, is NEVER marked live, so the FE keeps polling it. No silent dead inbox.

Manual IDLE: Python 3.11's ``imaplib`` has no native ``idle()`` (added in 3.13), so
:class:`ImapIdleConnection` drives it by hand over the stdlib client — send
``<tag> IDLE``, read untagged responses with a bounded socket timeout, send ``DONE``
to break, and RE-ISSUE before the server's ~29-minute IDLE limit. All blocking IMAP
work runs in a worker thread via ``asyncio.to_thread`` so the watcher stays a normal
cancellable async task; a ``threading.Event`` lets a long socket read unblock on stop.

Owner-scoping: watchers are keyed by ``(owner, account_id)`` and publish under the
account's own owner, so an owner never receives another owner's mail signal. The
account enumeration mirrors the existing multi-account fan-out in
``routes/email_pollers.py`` (every enabled account, its owner from the row).

The connection is injected (``conn_factory``) so hermetic tests drive a FAKE IMAP
with zero network; the real :class:`ImapIdleConnection` path is integration-only.
"""

from __future__ import annotations

import asyncio
import logging
import socket
import threading
import time
from typing import Any, Callable, Optional, Protocol

logger = logging.getLogger(__name__)


# --- connection seam --------------------------------------------------------


class IdleConnection(Protocol):
    """The minimal async surface an :class:`AccountWatcher` drives.

    The real adapter wraps blocking ``imaplib`` calls in ``asyncio.to_thread``; the
    test fake implements these directly with asyncio primitives (no threads, no net).
    """

    async def connect(self) -> None: ...
    async def has_idle(self) -> bool: ...
    async def select_inbox_count(self) -> int: ...
    async def wait_for_change(self, stop_event: threading.Event) -> str: ...
    async def close(self) -> None: ...


class ImapIdleConnection:
    """Real IDLE connection over stdlib ``imaplib`` (manual IDLE for 3.11/3.12).

    Every blocking op runs in a worker thread. ``wait_for_change`` issues IDLE and
    reads untagged responses with a short socket timeout, returning:
      * ``"new"``    — an EXISTS/RECENT untagged response arrived (new mail);
      * ``"timeout"``— the IDLE window elapsed with nothing (caller re-issues);
      * ``"closed"`` — the connection dropped / errored (caller reconnects).
    """

    # Re-issue IDLE well before the RFC-2177 ~29-minute server limit.
    IDLE_RESET_SECONDS = 29 * 60
    # Socket read timeout while idling — bounds how long a blocked read holds the
    # worker thread, so a stop signal is honored within this window.
    POLL_TIMEOUT_SECONDS = 30

    def __init__(self, owner: str, account_id: str) -> None:
        self.owner = owner
        self.account_id = account_id
        self._conn: Any = None

    async def connect(self) -> None:
        await asyncio.to_thread(self._connect)

    def _connect(self) -> None:
        # Reuse the existing owner-scoped IMAP connect (login + TLS mode selection).
        from routes.email_helpers import _imap_connect

        self._conn = _imap_connect(self.account_id, owner=self.owner)

    async def has_idle(self) -> bool:
        return await asyncio.to_thread(self._has_idle)

    def _has_idle(self) -> bool:
        caps = getattr(self._conn, "capabilities", ()) or ()
        # imaplib stores capabilities as a tuple of str on py3.
        return any(str(c).upper() == "IDLE" for c in caps)

    async def select_inbox_count(self) -> int:
        return await asyncio.to_thread(self._select_inbox_count)

    def _select_inbox_count(self) -> int:
        typ, data = self._conn.select("INBOX", readonly=True)
        if typ != "OK":
            raise RuntimeError(f"SELECT INBOX failed: {typ}")
        try:
            return int(data[0])
        except (TypeError, ValueError):
            return 0

    async def wait_for_change(self, stop_event: threading.Event) -> str:
        return await asyncio.to_thread(self._wait_for_change, stop_event)

    def _wait_for_change(self, stop_event: threading.Event) -> str:
        c = self._conn
        try:
            c.sock.settimeout(self.POLL_TIMEOUT_SECONDS)
        except Exception:
            pass
        tag = c._new_tag()
        try:
            c.send(tag + b" IDLE\r\n")
            # Server acknowledges with a continuation line ("+ idling").
            resp = c._get_line()
        except Exception:
            return "closed"
        if not resp or not resp.startswith(b"+"):
            # Server refused IDLE unexpectedly — treat as a dropped session.
            self._safe_done(tag)
            return "closed"

        started = time.monotonic()
        result = "timeout"
        while True:
            if stop_event.is_set():
                result = "timeout"
                break
            if time.monotonic() - started >= self.IDLE_RESET_SECONDS:
                result = "timeout"  # re-issue window reached; caller loops
                break
            try:
                line = c._get_line()
            except socket.timeout:
                continue  # nothing arrived this tick; keep idling
            except Exception:
                return "closed"
            if not line:
                return "closed"
            up = line.upper()
            if b"EXISTS" in up or b"RECENT" in up:
                result = "new"
                break

        # Break IDLE cleanly so the next command (or re-IDLE) works.
        if not self._safe_done(tag):
            # DONE/drain failed — the session is unusable; force a reconnect unless
            # we already have a real new-mail result to deliver first.
            return "new" if result == "new" else "closed"
        return result

    def _safe_done(self, tag: bytes) -> bool:
        """Send DONE and drain until the IDLE command's tagged completion. Returns
        False if the exchange failed (the connection should be considered closed)."""
        c = self._conn
        try:
            c.send(b"DONE\r\n")
        except Exception:
            return False
        deadline = time.monotonic() + self.POLL_TIMEOUT_SECONDS
        while True:
            try:
                line = c._get_line()
            except socket.timeout:
                if time.monotonic() > deadline:
                    return False
                continue
            except Exception:
                return False
            if not line:
                return False
            if line.startswith(tag):
                return True

    async def close(self) -> None:
        await asyncio.to_thread(self._close)

    def _close(self) -> None:
        conn = self._conn
        self._conn = None
        if conn is None:
            return
        try:
            conn.logout()
        except Exception:
            try:
                conn.shutdown()
            except Exception:
                pass


def _default_conn_factory(owner: str, account_id: str) -> ImapIdleConnection:
    return ImapIdleConnection(owner, account_id)


# --- account enumeration (mirrors email_pollers' multi-account fan-out) ------


def enumerate_idle_accounts() -> list[tuple[str, str]]:
    """Return ``(owner, account_id)`` for every enabled IMAP-configured account.

    Owner is normalized from the row (``None`` → ""). Only accounts with an IMAP
    host + user are returned; a bare/unconfigured row would just fail to connect and
    never go live anyway. Runs sync (called via ``asyncio.to_thread``)."""
    from core.database import SessionLocal, EmailAccount

    db = SessionLocal()
    try:
        rows = (
            db.query(EmailAccount)
            .filter(EmailAccount.enabled == True)  # noqa: E712
            .all()
        )
        out: list[tuple[str, str]] = []
        for r in rows:
            if not (r.imap_host and r.imap_user):
                continue
            out.append((r.owner or "", r.id))
        return out
    finally:
        db.close()


# --- per-account watcher ----------------------------------------------------


class AccountWatcher:
    """One persistent IDLE loop for a single ``(owner, account_id)``.

    Reconnects with exponential backoff. Marks the account live in the hub only while
    IDLE is established; on any failure (connect/login, non-IDLE server, mid-stream
    drop) it clears liveness so the FE keeps polling this account.
    """

    BASE_BACKOFF_SECONDS = 1.0
    MAX_BACKOFF_SECONDS = 60.0
    STOP_JOIN_TIMEOUT = ImapIdleConnection.POLL_TIMEOUT_SECONDS + 5

    def __init__(
        self,
        owner: str,
        account_id: str,
        hub: Any,
        conn_factory: Callable[[str, str], IdleConnection],
    ) -> None:
        self.owner = owner
        self.account_id = account_id
        self._hub = hub
        self._conn_factory = conn_factory
        self._stop = asyncio.Event()
        # A separate threading.Event so a blocked socket read (in a worker thread)
        # can unblock on stop even though the asyncio task is cancelled.
        self._thread_stop = threading.Event()
        self._task: Optional[asyncio.Task] = None

    def start(self) -> asyncio.Task:
        self._task = asyncio.create_task(self._run())
        return self._task

    async def stop(self) -> None:
        self._stop.set()
        self._thread_stop.set()
        task = self._task
        if task is None:
            return
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=self.STOP_JOIN_TIMEOUT)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    async def _run(self) -> None:
        backoff = self.BASE_BACKOFF_SECONDS
        try:
            while not self._stop.is_set():
                established = False
                conn = self._conn_factory(self.owner, self.account_id)
                try:
                    await conn.connect()
                    if not await conn.has_idle():
                        # Non-IDLE server: there is no live signal we can honestly
                        # emit. Give up so the FE keeps polling this account.
                        logger.info(
                            "email idle: account %s has no IDLE capability; "
                            "live push disabled (poll stays on)",
                            self.account_id,
                        )
                        return
                    await conn.select_inbox_count()
                    established = True
                    self._hub.set_account_live(self.owner, self.account_id, True)
                    backoff = self.BASE_BACKOFF_SECONDS
                    while not self._stop.is_set():
                        result = await conn.wait_for_change(self._thread_stop)
                        if self._stop.is_set():
                            break
                        if result == "new":
                            from src.email_events import unread_changed_frame

                            self._hub.publish(
                                self.owner, unread_changed_frame(self.account_id)
                            )
                        elif result == "closed":
                            break
                        # "timeout" → loop and re-issue IDLE.
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    # Never log credentials — only the account id + error type.
                    logger.info(
                        "email idle: watcher error for account %s: %s",
                        self.account_id,
                        type(e).__name__,
                    )
                finally:
                    if established:
                        self._hub.set_account_live(self.owner, self.account_id, False)
                    try:
                        await conn.close()
                    except Exception:
                        pass
                if self._stop.is_set():
                    break
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, self.MAX_BACKOFF_SECONDS)
        finally:
            # Belt-and-suspenders: never leave the account marked live on exit.
            self._hub.set_account_live(self.owner, self.account_id, False)


# --- manager ----------------------------------------------------------------


class EmailIdleManager:
    """Owns the set of :class:`AccountWatcher`s + the liveness heartbeat.

    Started non-blocking at app startup; stopped cleanly at shutdown (every watcher
    stops, closing its IMAP connection — no leaked sockets/threads). ``refresh``
    re-enumerates accounts so an add/remove is picked up without a restart.
    """

    HEARTBEAT_SECONDS = 25

    def __init__(
        self,
        hub: Any,
        conn_factory: Optional[Callable[[str, str], IdleConnection]] = None,
        account_source: Optional[Callable[[], list[tuple[str, str]]]] = None,
    ) -> None:
        self._hub = hub
        self._conn_factory = conn_factory or _default_conn_factory
        self._account_source = account_source or enumerate_idle_accounts
        self._watchers: dict[tuple[str, str], AccountWatcher] = {}
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        await self._sync_watchers()
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def refresh(self) -> None:
        """Re-enumerate accounts and add/remove watchers to match (idempotent)."""
        if not self._started:
            return
        await self._sync_watchers()

    async def _sync_watchers(self) -> None:
        try:
            accounts = await asyncio.to_thread(self._account_source)
        except Exception as e:
            logger.warning("email idle: account enumeration failed: %s", e)
            accounts = []
        desired = {(o, a) for (o, a) in accounts}

        for key in desired:
            if key not in self._watchers:
                w = AccountWatcher(key[0], key[1], self._hub, self._conn_factory)
                self._watchers[key] = w
                w.start()

        for key in list(self._watchers.keys()):
            if key not in desired:
                w = self._watchers.pop(key)
                await w.stop()

    async def _heartbeat_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(self.HEARTBEAT_SECONDS)
                try:
                    self._hub.heartbeat()
                except Exception:  # pragma: no cover - heartbeat must never crash
                    pass
        except asyncio.CancelledError:
            pass

    async def stop(self) -> None:
        self._started = False
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except (asyncio.CancelledError, Exception):
                pass
            self._heartbeat_task = None
        watchers = list(self._watchers.values())
        self._watchers.clear()
        # Stop every watcher concurrently — each AccountWatcher.stop() can wait out
        # a drain window (~35s), so awaiting them serially would make shutdown scale
        # linearly with the account count. gather bounds it to one watcher's window.
        # return_exceptions keeps the prior behaviour of ignoring individual failures.
        if watchers:
            await asyncio.gather(*(w.stop() for w in watchers), return_exceptions=True)

    @property
    def watcher_count(self) -> int:
        return len(self._watchers)
