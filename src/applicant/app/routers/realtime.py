"""Realtime WebSocket backbone — engine side (spec: realtime-websocket.md, Phase 1).

A single multiplexed duplex socket per session speaking the frame envelope
``{chan, type, seq, data}``. The engine is the internal ``api`` service (never
public), so this endpoint carries NO cookie auth of its own — exactly like the
existing engine HTTP surface, it trusts the private in-network hop and the real
owner-scoping happens at the public workspace front-door upgrade. What it DOES
enforce is the safety seam: every upstream frame is authorized server-side via
:func:`applicant.core.realtime.envelope.authorize_upstream` (default-deny), so a
crafted command can never bypass the review-before-submit stop-boundary.

Phase 1 implements only the ``presence`` channel end-to-end (join / leave / count)
to prove the round-trip; the consequential channels are refused by the seam until
their phase wires them through the core rules.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from applicant.app.realtime import RealtimeRegistry, get_registry
from applicant.core.realtime.envelope import control_frame, parse_frame

logger = logging.getLogger(__name__)

router = APIRouter(tags=["realtime"])

#: Default session key. The engine is single-tenant, so the workspace bridge
#: passes the one owner's key; a bare direct connection (tests / diagnostics)
#: lands on ``default``.
_DEFAULT_SESSION = "default"


def _parse_resume(raw: str | None) -> dict[str, int]:
    """Decode the ``resume`` query param (``chan:seq`` pairs) into ``{chan: seq}``.

    Malformed pairs are skipped, never raised — a bad resume hint at worst
    replays from the start, it must not fail the upgrade.
    """
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


@router.websocket("/api/realtime/ws")
async def realtime_ws(ws: WebSocket) -> None:
    await ws.accept()
    registry: RealtimeRegistry = get_registry()
    session_id = ws.query_params.get("session") or _DEFAULT_SESSION
    resume = _parse_resume(ws.query_params.get("resume"))
    session = registry.get_or_create(session_id)
    queue = session.attach(resume)

    # ``hello`` tells the client the socket is live + which session it is on. It
    # rides the same queue so the single writer task is the ONLY sender (Starlette
    # WebSocket.send is not safe to call from two coroutines at once).
    queue.put_nowait(control_frame("hello", {"session": session_id}))

    async def _writer() -> None:
        # Dedup feature-channel frames by seq so an attach-time replay that races a
        # live publish is delivered exactly once per channel. ``sys`` control frames
        # (seq -1) are always passed through.
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
            decision = session.apply_upstream(frame)
            if not decision.allowed:
                queue.put_nowait(
                    control_frame(
                        "error",
                        {"chan": frame.chan, "type": frame.type, "reason": decision.reason},
                    )
                )
    except WebSocketDisconnect:
        pass
    except Exception:  # pragma: no cover - defensive: never leak a traceback over the socket
        logger.warning("realtime ws error on session %s", session_id, exc_info=True)
    finally:
        writer_task.cancel()
        session.detach(queue)
        registry.maybe_evict(session_id)
