# routes/shell_ws_routes.py
"""Cookbook shell/download progress streaming over a WebSocket (SSE-parity).

Today the Cookbook download panel streams shell output over SSE: ``POST
/api/shell/stream`` runs a command and returns a ``StreamingResponse`` of
``data: {...}\\n\\n`` events (``routes/shell_routes.py``). ``cookbookDownload.js``
consumes ``res.body.getReader()`` in a line-splitting loop.

This module exposes the **same** command-stream over a WebSocket so the FE can
consume progress over a duplex socket, with SSE kept as the automatic fallback
lane. The socket runs the EXACT same generator the SSE route runs — there is no
NEW authority: it is the same admin-gated ``/api/shell/stream`` capability over a
different transport, dispatched through the shared ``build_shell_stream`` factory
so both emit byte-identical events.

Durability: unlike the chat WS (which subscribes to ``agent_runs``' durable
replay buffer), the shell stream has **no** replay buffer — each run spawns a
fresh subprocess bound to the live connection (the tmux path tails a logfile but
the download panel never uses it). So this relay exposes the generator directly
with the same event shape; there is nothing to resume to, and a mid-stream socket
drop ends the run exactly as an SSE disconnect always has (the disconnect probe
kills the subprocess). The FE therefore chooses WS at connect time and falls back
to SSE if the socket can't be established — it never re-runs the command.

Auth: the upgrade is authenticated by the ``applicant_session`` cookie (the HTTP
auth middleware never runs for WebSocket scopes) and gated to an **admin** user,
mirroring ``routes.shell_routes._require_admin`` (shell exec is admin-only —
never a regular-user surface). An unauthenticated or non-admin upgrade is
rejected before any command runs.
"""

from __future__ import annotations

import asyncio
import logging
import os

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from routes.shell_routes import STREAM_TIMEOUT, build_shell_stream
from src.applicant_realtime import _ws_is_trusted_loopback, SESSION_COOKIE

logger = logging.getLogger(__name__)

# Close codes (RFC 6455 private range) the FE reads to decide fallback.
_CLOSE_UNAUTHORIZED = 4401


def _resolve_ws_admin(ws: WebSocket) -> tuple[bool, str | None]:
    """Authenticate a shell-WS upgrade by the ``applicant_session`` cookie and
    gate it to an admin, mirroring ``routes.shell_routes._require_admin``.

    Fails closed in every mode:
    - Configured: the cookie must resolve to a real ADMIN user.
    - Unconfigured / first-run (no admin yet): only a DIRECT loopback caller (no
      proxy-forward headers), or ``AUTH_ENABLED=false``, is trusted — same rule
      ``_require_admin`` applies when no auth manager is configured. Never open to
      everyone just because setup hasn't happened.

    Returns ``(ok, username)``; ``ok`` is False so the caller closes the handshake
    BEFORE accept (nothing runs for a non-admin upgrade).
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

    # A configured, authenticated admin passes on any transport (proxied or not).
    if username and auth_mgr is not None:
        try:
            if auth_mgr.is_admin(username):
                return True, username
        except Exception:
            return False, None

    # Unconfigured / first-run: no admin exists yet. Trust only a direct loopback
    # caller (or the explicit AUTH_ENABLED=false escape hatch), as the "" owner.
    if not configured:
        if os.getenv("AUTH_ENABLED", "true").lower() == "false":
            return True, ""
        if _ws_is_trusted_loopback(ws):
            return True, ""
    return False, None


class _WsDisconnectProbe:
    """Duck-typed ``Request`` stand-in exposing ``is_disconnected()``.

    The shell generators (``_generate_pipe``/``_generate_pty``/``_generate_tmux``)
    only ever call ``request.is_disconnected()`` to notice a dropped client and
    kill the subprocess. A background watcher flips ``_closed`` when the WS client
    goes away, so the generator tears the run down on either transport.
    """

    def __init__(self) -> None:
        self._closed = False

    def mark_closed(self) -> None:
        self._closed = True

    async def is_disconnected(self) -> bool:
        return self._closed


async def _watch_ws_close(ws: WebSocket, probe: _WsDisconnectProbe) -> None:
    """Watch for the client closing the socket and flag the disconnect probe.

    Runs concurrently with the send loop (Starlette allows simultaneous
    send/receive). A client close raises ``WebSocketDisconnect`` (or yields a
    ``websocket.disconnect`` message); either way we mark the probe so the
    generator's ``is_disconnected()`` check kills the subprocess even during a
    long output gap where no ``send_json`` would otherwise fail.
    """
    try:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break
    except Exception:
        pass
    finally:
        probe.mark_closed()


def _parse_timeout(raw) -> int:
    if raw is None:
        return STREAM_TIMEOUT
    try:
        return int(raw)
    except (TypeError, ValueError):
        return STREAM_TIMEOUT


def setup_shell_ws_routes() -> APIRouter:
    router = APIRouter(tags=["shell-ws"])

    @router.websocket("/api/shell/ws")
    async def shell_ws(ws: WebSocket) -> None:
        # Auth on upgrade — reject BEFORE accept so nothing runs for a
        # non-admin caller.
        ok, _user = _resolve_ws_admin(ws)
        if not ok:
            await ws.close(code=_CLOSE_UNAUTHORIZED)
            return
        await ws.accept()

        # First frame carries the command to run. This is the SAME payload the
        # SSE POST body carries, gated by the SAME admin check — no new authority.
        try:
            first = await ws.receive_json()
        except (WebSocketDisconnect, Exception):
            await ws.close()
            return

        if not isinstance(first, dict) or first.get("type") != "run":
            await ws.send_json({"type": "error", "error": "expected a run frame"})
            await ws.close()
            return

        cmd = str(first.get("command") or "").strip()
        if not cmd:
            await ws.send_json({"type": "error", "error": "no command provided"})
            await ws.close()
            return

        timeout = _parse_timeout(first.get("timeout"))
        use_pty = bool(first.get("use_pty"))
        use_tmux = bool(first.get("use_tmux"))

        # Acknowledge the accepted run BEFORE the command starts, so the FE commits
        # to the WS immediately. Otherwise a valid command that produces no output
        # for a while would let the FE's connect-timeout fire and issue the SSE
        # fallback POST — running the SAME command a SECOND time. The ack is the
        # server's "I've got it, I'm about to run it" so the FE never falls back.
        try:
            await ws.send_json({"type": "ack"})
        except Exception:
            await ws.close()
            return

        probe = _WsDisconnectProbe()
        watcher = asyncio.create_task(_watch_ws_close(ws, probe))
        gen = build_shell_stream(cmd, timeout, use_pty, use_tmux, probe)
        idx = 0
        try:
            async for ev in gen:
                try:
                    await ws.send_json({"type": "chunk", "seq": idx, "data": ev})
                except Exception:
                    # Client dropped mid-stream — stop relaying; the probe/finally
                    # tears down the subprocess (no buffer to resume, same as SSE).
                    break
                idx += 1
            try:
                await ws.send_json({"type": "end", "seq": idx})
            except Exception:
                pass
        except WebSocketDisconnect:
            pass
        except Exception:  # pragma: no cover - never leak a traceback over the socket
            logger.warning("shell ws error", exc_info=True)
        finally:
            probe.mark_closed()
            watcher.cancel()
            try:
                await gen.aclose()
            except Exception:  # pragma: no cover
                pass
            try:
                await ws.close()
            except Exception:  # pragma: no cover
                pass

    return router
