"""Shared deep-research stream helpers — owner-scope + the progress-event
generator — used by BOTH the SSE route (``routes/research_routes.py``) and the
WebSocket relay (``routes/research_ws_routes.py``) so the stream's event shape
and owner-scope can NEVER drift between the two transports.

Kept deliberately dependency-light: the heavy DB / ``core.safe_path`` import
(which pulls the whole ``core`` package + DB init) is deferred to call time in the
disk-fallback branch of ``research_owns``, so importing this module — and hence
the WS relay — is hermetic (no DB required at import).
"""

from __future__ import annotations

import asyncio
import json
import logging

logger = logging.getLogger(__name__)


def research_owns(research_handler, session_id: str, user: str) -> bool:
    """Owner-scope a research session to ``user`` — the single source of truth
    shared by the SSE route's ``_owns_in_memory`` closure and the WS relay.
    Prefers the in-flight (in-memory) task's stamped owner and falls back to the
    persisted JSON's ``owner`` once the task has left memory. A missing / unsafe
    id or a foreign owner returns False so callers 404 (never 403 — don't leak
    that the report exists)."""
    entry = research_handler._active_tasks.get(session_id)
    if entry is not None:
        return entry.get("owner", "") == user
    # Task no longer in memory — check the persisted JSON. Import the path helper
    # lazily so this module stays importable without the DB / core package.
    from routes.research_routes import _safe_research_path

    path = _safe_research_path(session_id)
    if path is None or not path.exists():
        return False
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("owner") == user
    except Exception:
        logger.warning("Bare exception in research_stream.py")
        return False


async def research_event_payloads(research_handler, session_id: str):
    """Async generator of research-progress payloads for ``session_id`` — the
    SINGLE source of truth for the stream's event shape.

    Each yielded dict is one client-facing event:
      * a progress snapshot ``{**progress, "status": st}`` whenever it changes,
      * a terminal ``{"status": st, "final": True[, "error": ...]}`` once the run
        leaves the running state, then the generator returns,
      * ``{"status": "not_found"}`` if the session is unknown.

    NOTE: research is NOT backed by a durable append-only event buffer (unlike
    ``src/agent_runs.py``). It is a LIVE poll over the handler's in-memory task
    registry, and every payload is an IDEMPOTENT full-state snapshot rather than a
    delta. That is why a WS reconnect can simply re-subscribe and take the current
    snapshot — the newest snapshot supersedes all prior ones, so recovery is
    inherently gap-free without a per-event replay log."""
    last_progress = None
    while True:
        status = research_handler.get_status(session_id)
        if status is None:
            yield {"status": "not_found"}
            return
        st = status.get("status", "")
        progress = status.get("progress", {})
        if progress != last_progress:
            last_progress = progress
            yield {**progress, "status": st}
        if st != "running":
            final = {"status": st, "final": True}
            task = research_handler._active_tasks.get(session_id, {})
            if st == "error" and task.get("result"):
                final["error"] = str(task["result"])[:500]
            yield final
            return
        await asyncio.sleep(1.5)
