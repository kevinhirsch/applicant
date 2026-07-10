# routes/email_events_ws_routes.py
"""Front-door email-events WebSocket endpoint — the browser end of the IMAP-IDLE relay.

``/api/email/events/ws`` is a one-way (server→browser) owner-scoped push. The upgrade
is authenticated by the ``applicant_session`` cookie and scoped to the caller's OWN
owner, exactly like the SSE/chat-WS paths (the ``BaseHTTPMiddleware`` auth gate never
runs for WebSocket scopes, which is why the handshake authenticates itself). An
unauthenticated upgrade is rejected BEFORE accept so no push opens for it.

On connect the socket sends ``hello`` then the current liveness (``live``/``down``).
Thereafter it relays this owner's frames from the :class:`EmailEventsHub` — a
``live`` heartbeat and ``email:unread-changed`` nudges — so the FE can suppress its
unread poll WHILE the push is genuinely live and restore it the moment it isn't. The
socket carries NO upstream verb and adds no authority; the browser still reads mail
over the existing owner-gated HTTP email routes.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.email_events import (
    get_email_events_hub,
    hello_frame,
    live_frame,
    resolve_ws_email_user,
)

logger = logging.getLogger(__name__)

# Close code (RFC 6455 private range) the FE reads to decide fallback.
_CLOSE_UNAUTHORIZED = 4401


def setup_email_events_ws_routes() -> APIRouter:
    router = APIRouter(tags=["email-events-ws"])

    @router.websocket("/api/email/events/ws")
    async def email_events_ws(ws: WebSocket) -> None:
        # Auth on upgrade — reject BEFORE accept so nothing pushes for a
        # non-authenticated caller. Owner-scoped to the caller's own owner.
        ok, owner = resolve_ws_email_user(ws)
        if not ok or owner is None:
            await ws.close(code=_CLOSE_UNAUTHORIZED)
            return
        await ws.accept()

        hub = get_email_events_hub(ws.app)
        queue = hub.attach(owner)
        # Greet + report the current liveness level so a socket that connects AFTER
        # the watcher is already live isn't stuck waiting for the next transition.
        queue.put_nowait(hello_frame(owner))
        queue.put_nowait(live_frame(hub.is_live(owner)))

        async def _writer() -> None:
            while True:
                frame = await queue.get()
                await ws.send_json(frame)

        writer_task = asyncio.create_task(_writer())
        try:
            # The socket has no upstream verb — receiving only detects the client
            # going away (mirrors the shell-WS disconnect watcher).
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        except Exception:  # pragma: no cover - never leak a traceback over the socket
            logger.warning("email events ws error (owner=%s)", owner, exc_info=True)
        finally:
            writer_task.cancel()
            hub.detach(owner, queue)
            try:
                await ws.close()
            except Exception:  # pragma: no cover
                pass

    return router
