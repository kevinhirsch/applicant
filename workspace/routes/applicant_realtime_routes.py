# routes/applicant_realtime_routes.py
"""Front-door realtime WebSocket endpoint (realtime-websocket.md, Phase 1).

The ONE public WebSocket: ``/api/applicant/realtime/ws``. It authenticates the
upgrade by the existing ``applicant_session`` cookie, owner-scoped exactly like
the HTTP proxies (``require_engine_owner`` semantics) — an unauthenticated or
non-owner upgrade is rejected BEFORE the socket is accepted, so no channel ever
opens for it. A valid owner is attached to their (single) session, which opens
one multiplexed bridge WS to the engine and fans the ``{chan,type,seq,data}``
envelope both ways. Many tabs of the one owner share that session (1 session : N
sockets); a reconnecting tab replays its per-channel buffer then goes live.

Safety: the workspace is thin transport. It validates envelope SHAPE and forwards
upstream frames to the engine, which is the single authority that authorizes
every upstream command server-side (default-deny) — the socket adds no authority
the owner doesn't already have over HTTP and cannot bypass the review-before-submit
stop-boundary. The auth gate here never runs in ``BaseHTTPMiddleware`` (it skips
WebSocket scopes), which is exactly why this endpoint authenticates the handshake
itself.
"""

from __future__ import annotations

import asyncio
import logging
import secrets

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.applicant_realtime import (
    control_frame,
    get_hub,
    parse_frame,
    resolve_ws_owner,
)

logger = logging.getLogger(__name__)

# Close codes (RFC 6455 private range 4000-4999) the FE reads to decide fallback.
_CLOSE_UNAUTHORIZED = 4401


def _parse_resume(raw: str | None) -> dict[str, int]:
    """Decode the ``resume`` query param (``chan:seq`` pairs) into ``{chan: seq}``."""
    out: dict[str, int] = {}
    if not raw:
        return out
    for pair in raw.split(","):
        chan, _, seq = pair.partition(":")
        chan = chan.strip()
        try:
            if chan and seq:
                out[chan] = int(seq)
        except ValueError:
            continue
    return out


def setup_applicant_realtime_routes() -> APIRouter:
    router = APIRouter(prefix="/api/applicant/realtime", tags=["applicant-realtime"])

    @router.websocket("/ws")
    async def applicant_realtime_ws(ws: WebSocket) -> None:
        # Auth on upgrade — reject BEFORE accept so no channel opens for a
        # non-owner. Owner-scoped identically to require_engine_owner.
        ok, owner = resolve_ws_owner(ws)
        if not ok:
            await ws.close(code=_CLOSE_UNAUTHORIZED)
            return
        await ws.accept()

        session_id = owner or "owner"
        tab = ws.query_params.get("tab") or secrets.token_hex(4)
        resume = _parse_resume(ws.query_params.get("resume"))

        hub = get_hub(ws.app)
        session = hub.get_or_create(session_id)
        session.ensure_bridge()
        queue = session.attach(resume)
        queue.put_nowait(control_frame("hello", {"session": session_id, "tab": tab}))
        await session.add_tab(tab)

        async def _writer() -> None:
            # Sole sender to this socket; dedup feature-channel frames by seq so a
            # replay that races a live relay is delivered once. sys frames pass.
            sent: dict[str, int] = {}
            while True:
                frame = await queue.get()
                seq = frame.get("seq", -1)
                chan = frame.get("chan", "")
                if isinstance(seq, int) and seq >= 0:
                    if sent.get(chan, -1) >= seq:
                        continue
                    sent[chan] = seq
                await ws.send_json(frame)

        writer_task = asyncio.create_task(_writer())
        try:
            while True:
                raw = await ws.receive_json()
                try:
                    frame = parse_frame(raw)
                except ValueError as exc:
                    queue.put_nowait(control_frame("error", {"reason": str(exc)}))
                    continue
                # Forward to the engine — it authorizes every upstream command.
                await session.send_upstream(frame)
        except WebSocketDisconnect:
            pass
        except Exception:  # pragma: no cover - never leak a traceback over the socket
            logger.warning("applicant realtime ws error (session=%s)", session_id, exc_info=True)
        finally:
            writer_task.cancel()
            session.detach(queue)
            await session.remove_tab(tab)
            await hub.release(session_id)

    return router
