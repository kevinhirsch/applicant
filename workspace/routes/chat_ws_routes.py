# routes/chat_ws_routes.py
"""Workspace-native chat streaming over a WebSocket (SSE-parity transport).

Today the front-door chat streams over SSE: ``POST /api/chat_stream`` starts a
DETACHED agent/chat run (``src/agent_runs.py`` drains the generator into a
per-session replay buffer) and returns ``StreamingResponse(agent_runs.subscribe)``;
``GET /api/chat/resume/{sid}`` re-subscribes for reconnect. This is the
**workspace-native** chat pipeline (browser ⇄ workspace LLM streaming), NOT the
applicant-engine bridge (``/api/applicant/realtime/ws``) — the engine-backed Job
Assistant has its own non-streaming path.

This module exposes the **same** ``agent_runs`` stream over a WebSocket so the FE
can consume tokens/events over a duplex socket, with SSE kept as the automatic
fallback lane. The socket is PURE READ-TRANSPORT:

* Message SEND is unchanged — the browser still ``POST``s ``/api/chat_stream``,
  which runs through the exact same chat handler + gates and starts the detached
  run. The WS adds no send authority and no new consequential action.
* The WS only SUBSCRIBES to an already-started run's replay buffer and relays
  each buffered SSE event string to the client, then a terminal ``end`` frame.
  A reconnect replays the buffered tail (via the ``resume`` offset) then goes
  live — identical durability to the SSE ``/api/chat/resume`` path, since both
  read the SAME ``agent_runs`` buffer.

Auth: the upgrade is authenticated by the ``applicant_session`` cookie (the HTTP
auth middleware never runs for WebSocket scopes) and then owner-scoped to the
session exactly like the SSE path's ``_verify_session_owner`` — an
unauthenticated or non-owning upgrade is rejected before any event is sent.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src import agent_runs
from src.applicant_realtime import _ws_is_trusted_loopback, SESSION_COOKIE

logger = logging.getLogger(__name__)

# Close codes (RFC 6455 private range) the FE reads to decide fallback.
_CLOSE_UNAUTHORIZED = 4401
_CLOSE_NOT_FOUND = 4404


def _resolve_ws_chat_user(ws: WebSocket) -> tuple[bool, str | None]:
    """Authenticate a chat-WS upgrade by the ``applicant_session`` cookie.

    Mirrors the SSE path's request auth (any authenticated user; per-session
    ownership is checked separately) but for the WebSocket handshake, which the
    ``BaseHTTPMiddleware`` auth gate never runs for. Returns ``(ok, username)``;
    ``ok`` is False for an unauthenticated upgrade so the caller closes the
    handshake BEFORE accepting. In unconfigured first-run mode a DIRECT loopback
    caller passes as the empty-string owner (matching ``require_user``).
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
    # headers) is trusted, as the empty-string owner.
    if not configured and _ws_is_trusted_loopback(ws):
        return True, ""
    return False, None


def _ws_user_owns_session(user: str, session_id: str) -> bool:
    """Owner-scope a chat-WS subscribe to the session, mirroring
    ``routes.session_routes._verify_session_owner`` (which the SSE path uses).

    Isolated in a module-level function so the transport seam is unit-testable
    without a real DB. Returns False for a missing or foreign-owned session.
    """
    from core.database import SessionLocal, Session as DbSession

    db = SessionLocal()
    try:
        row = db.query(DbSession.owner).filter(DbSession.id == session_id).first()
        if not row:
            return False
        owner = row.owner
        if owner == user:
            return True
        # Unconfigured first-run loopback owner ("") may own a null-owner session.
        if user == "" and (owner is None or owner == ""):
            return True
        return False
    finally:
        db.close()


def setup_chat_ws_routes() -> APIRouter:
    router = APIRouter(tags=["chat-ws"])

    @router.websocket("/api/chat/ws")
    async def chat_ws(ws: WebSocket) -> None:
        # Auth on upgrade — reject BEFORE accept so nothing streams for a
        # non-authenticated caller.
        ok, user = _resolve_ws_chat_user(ws)
        if not ok or user is None:
            await ws.close(code=_CLOSE_UNAUTHORIZED)
            return
        await ws.accept()

        # First frame selects the session to subscribe to and how far the client
        # has already consumed (replay offset). This is the ONLY upstream verb —
        # a subscribe. There is no send verb here; message SEND stays on the HTTP
        # chat handler, so the socket adds no authority.
        try:
            first = await ws.receive_json()
        except (WebSocketDisconnect, Exception):
            await ws.close()
            return

        if not isinstance(first, dict) or first.get("type") != "subscribe":
            await ws.send_json({"type": "error", "error": "expected a subscribe frame"})
            await ws.close()
            return

        session_id = str(first.get("session") or "").strip()
        try:
            resume = int(first.get("resume") or 0)
        except (TypeError, ValueError):
            resume = 0
        if resume < 0:
            resume = 0
        if not session_id:
            await ws.send_json({"type": "error", "error": "missing session"})
            await ws.close()
            return

        # Owner-scope exactly like the SSE path. A foreign / missing session is
        # refused (same 404 semantics as _verify_session_owner).
        if not _ws_user_owns_session(user, session_id):
            await ws.send_json({"type": "error", "error": "session not found"})
            await ws.close(code=_CLOSE_NOT_FOUND)
            return

        # Relay the SAME agent_runs replay buffer the SSE path serves: replay the
        # buffered tail from `resume`, then go live, then a terminal `end`. If the
        # run isn't (or is no longer) active, subscribe() yields nothing and the
        # client gets an immediate `end` (it then reloads history / falls back).
        idx = 0
        agen = agent_runs.subscribe(session_id)
        try:
            async for ev in agen:
                if idx < resume:
                    idx += 1
                    continue
                await ws.send_json({"type": "chunk", "seq": idx, "data": ev})
                idx += 1
            try:
                await ws.send_json({"type": "end", "seq": idx})
            except Exception:
                pass
        except WebSocketDisconnect:
            # Client dropped — closing the socket only drops this subscriber; the
            # detached run keeps going and saves on completion (durability).
            pass
        except Exception:  # pragma: no cover - never leak a traceback over the socket
            logger.warning("chat ws error (session=%s)", session_id, exc_info=True)
        finally:
            try:
                await agen.aclose()
            except Exception:  # pragma: no cover
                pass
            try:
                await ws.close()
            except Exception:  # pragma: no cover
                pass

    return router
