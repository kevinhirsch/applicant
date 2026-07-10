# routes/research_ws_routes.py
"""Deep-research progress stream over a WebSocket (SSE-parity transport).

Today the research panel streams progress over SSE: ``GET
/api/research/stream/{session_id}`` returns a ``StreamingResponse`` that polls
``research_handler.get_status`` every ~1.5s and emits ``data: {...}`` events. This
module exposes the **same** stream over a WebSocket so the FE can consume it over
a duplex socket, with the SSE ``EventSource`` kept as the automatic fallback lane
(an honesty invariant — never a silent dead UI).

The socket is PURE READ-TRANSPORT and adds NO authority:

* Research is STARTED unchanged — the browser still ``POST``s
  ``/api/research/start`` (privilege-gated ``can_use_research``), which runs the
  background task. The WS adds no start/cancel verb; the only upstream verb is a
  ``subscribe``.
* The WS relays the SAME payloads the SSE route serves (``research_event_payloads``
  in ``routes/research_routes.py`` is the single source of the event shape), each
  as a ``{"type": "event", "seq": N, "data": {...}}`` frame, then a terminal
  ``{"type": "end"}``.

Durability / replay: unlike ``src/agent_runs.py`` (a durable append-only replay
buffer), research is a LIVE poll over the handler's in-memory task registry and
each payload is an IDEMPOTENT full-state snapshot, not a delta. So a reconnect
simply re-subscribes and takes the current snapshot — recovery is inherently
gap-free without a per-event log. The ``resume`` offset is accepted for protocol
parity with the chat WS and skips already-delivered seqs within a single
stream, but the FE reconnects at ``resume=0`` and relies on snapshot idempotency.

Auth: the upgrade is authenticated by the ``applicant_session`` cookie (the HTTP
auth middleware never runs for WebSocket scopes) and then owner-scoped to the
session exactly like the SSE path's ``_owns_in_memory`` (both call
``research_owns``) — an unauthenticated or non-owning upgrade is rejected before
any event is sent.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

# Reuse the chat-WS cookie-auth resolver verbatim — it authenticates ANY logged-in
# user (per-session ownership is a separate check), which is exactly what the
# research stream's ``_require_user`` gate does. Lift-and-shift, don't rebuild.
from routes.chat_ws_routes import _resolve_ws_chat_user as _resolve_ws_user
# Import from the dependency-light shared module (NOT routes.research_routes,
# which pulls heavy DB/endpoint imports at module load) so this WS relay stays
# hermetically importable — same event shape + owner-scope the SSE route uses.
from routes.research_stream import research_event_payloads, research_owns

logger = logging.getLogger(__name__)

# Close codes (RFC 6455 private range) the FE reads to decide fallback.
_CLOSE_UNAUTHORIZED = 4401
_CLOSE_NOT_FOUND = 4404


def setup_research_ws_routes(research_handler) -> APIRouter:
    router = APIRouter(tags=["research-ws"])

    @router.websocket("/api/research/ws")
    async def research_ws(ws: WebSocket) -> None:
        # Auth on upgrade — reject BEFORE accept so nothing streams for a
        # non-authenticated caller.
        ok, user = _resolve_ws_user(ws)
        if not ok or user is None:
            await ws.close(code=_CLOSE_UNAUTHORIZED)
            return
        await ws.accept()

        # First frame selects the session to subscribe to and how far the client
        # has already consumed (replay offset). This is the ONLY upstream verb —
        # a subscribe. There is no start/cancel verb here; those stay on the HTTP
        # research routes, so the socket adds no authority.
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

        # Owner-scope exactly like the SSE path (both call ``research_owns``). A
        # foreign / missing session is refused (same 404 semantics as the SSE
        # ``_owns_in_memory`` gate) — 404-not-403 so we don't leak existence.
        if not research_owns(research_handler, session_id, user):
            await ws.send_json({"type": "error", "error": "research not found"})
            await ws.close(code=_CLOSE_NOT_FOUND)
            return

        # Relay the SAME payloads the SSE path serves: each progress snapshot,
        # then the terminal payload, then a terminal `end`. If the session is
        # unknown the generator yields a single {"status": "not_found"} then ends
        # — the FE finishes the job as error (and can fall back / reload).
        idx = 0
        agen = research_event_payloads(research_handler, session_id)
        try:
            async for payload in agen:
                if idx < resume:
                    idx += 1
                    continue
                await ws.send_json({"type": "event", "seq": idx, "data": payload})
                idx += 1
            try:
                await ws.send_json({"type": "end", "seq": idx})
            except Exception:
                pass
        except WebSocketDisconnect:
            # Client dropped — closing the socket only drops this subscriber; the
            # background research task keeps running and persists on completion.
            pass
        except Exception:  # pragma: no cover - never leak a traceback over the socket
            logger.warning("research ws error (session=%s)", session_id, exc_info=True)
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
