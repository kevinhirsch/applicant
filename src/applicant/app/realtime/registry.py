"""Per-session, per-channel replay buffer + subscriber bus (lifted from agent_runs).

``workspace/src/agent_runs.py`` already implements the exact mechanic for ONE
stream: a buffer + a set of subscriber queues, publish fans out, a reconnecting
client replays the buffer then goes live, and a grace timer evicts idle state to
bound memory. This lifts that into a general :class:`RealtimeSession` that keeps a
buffer + subscriber-set **per channel**, plus the presence-member set the Phase-1
``presence`` channel is authoritative for.

Everything here is transport infrastructure (asyncio queues, in-memory buffers).
The *safety* decision — may an upstream command run? — lives in the pure core
(:mod:`applicant.core.realtime.envelope`); this module only asks it.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from applicant.core.realtime.envelope import Frame, UpstreamDecision, authorize_upstream

logger = logging.getLogger(__name__)

#: How long an idle session (no subscribers) is retained before its buffers +
#: presence set are evicted, so a reconnect within the window still replays.
#: Mirrors ``agent_runs._EVICT_GRACE_S``.
_EVICT_GRACE_S = 180.0


class RealtimeSession:
    """One owner's live session: N sockets attach, per-channel replay + presence."""

    __slots__ = ("session_id", "channels", "subscribers", "presence", "evict_task")

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        # chan -> ordered list of frame dicts; a frame's ``seq`` == its index, so
        # the buffer is both the replay log and the seq authority for the channel.
        self.channels: dict[str, list[dict[str, Any]]] = {}
        self.subscribers: set[asyncio.Queue] = set()
        self.presence: set[str] = set()
        self.evict_task: asyncio.Task | None = None

    # -- fan-out -----------------------------------------------------------

    def publish(self, chan: str, mtype: str, data: dict[str, Any]) -> dict[str, Any]:
        """Append a server-originated frame to its channel buffer and fan it out.

        Assigns the next monotonic ``seq`` for ``chan`` (== buffer index) so the
        sequence is gap-free and reconnect-resumable.
        """
        buf = self.channels.setdefault(chan, [])
        frame = {"chan": chan, "type": mtype, "seq": len(buf), "data": data}
        buf.append(frame)
        for q in list(self.subscribers):
            try:
                q.put_nowait(frame)
            except Exception:  # pragma: no cover - a full/broken queue must not break others
                pass
        return frame

    def attach(self, resume: dict[str, int] | None = None) -> asyncio.Queue:
        """Register a subscriber and enqueue the replay tail for each channel.

        Registered BEFORE the replay snapshot so a concurrent :meth:`publish`
        cannot slip between replay and live (at worst a frame is delivered twice —
        the writer dedups by ``seq``). ``resume`` maps ``chan -> last seq the
        socket already has``; only frames after it are replayed (gap-free, no
        dupes on a clean reconnect).
        """
        q: asyncio.Queue = asyncio.Queue()
        self.subscribers.add(q)
        if self.evict_task and not self.evict_task.done():
            self.evict_task.cancel()
        resume = resume or {}
        for chan, buf in self.channels.items():
            start = resume.get(chan, -1) + 1
            if start < 0:
                start = 0
            for frame in buf[start:]:
                q.put_nowait(frame)
        return q

    def detach(self, q: asyncio.Queue) -> None:
        self.subscribers.discard(q)

    # -- upstream (client -> server) --------------------------------------

    def apply_upstream(self, frame: Frame) -> UpstreamDecision:
        """Authorize an upstream frame via the core seam, then apply it if allowed.

        Phase 1 only implements the ``presence`` verbs. A denied frame mutates
        NOTHING and returns the decision so the endpoint can send the reason back
        to just that socket. This is the single server-side choke point later
        phases extend — never gate it on a caller-supplied flag.
        """
        decision = authorize_upstream(frame.chan, frame.type)
        if not decision.allowed:
            return decision
        if frame.chan == "presence":
            self._apply_presence(frame)
        return decision

    def _apply_presence(self, frame: Frame) -> None:
        data = frame.data or {}
        if frame.type == "join":
            self.presence.add(str(data.get("tab", "")))
        elif frame.type == "leave":
            self.presence.discard(str(data.get("tab", "")))
        elif frame.type == "sync":
            members = data.get("members") or []
            self.presence = {str(m) for m in members if str(m)}
        elif frame.type == "ping":
            pass  # keep-alive: no state change, but still re-broadcasts the count
        self.presence.discard("")
        self.publish(
            "presence",
            "state",
            {"count": len(self.presence), "members": sorted(self.presence)},
        )


class RealtimeRegistry:
    """Process-lived map of ``session_id -> RealtimeSession`` with grace eviction."""

    def __init__(self, evict_grace_s: float = _EVICT_GRACE_S) -> None:
        self._sessions: dict[str, RealtimeSession] = {}
        self._grace = evict_grace_s

    def get_or_create(self, session_id: str) -> RealtimeSession:
        sess = self._sessions.get(session_id)
        if sess is None:
            sess = RealtimeSession(session_id)
            self._sessions[session_id] = sess
        return sess

    def get(self, session_id: str) -> RealtimeSession | None:
        return self._sessions.get(session_id)

    def maybe_evict(self, session_id: str) -> None:
        """Arm a grace-period eviction for a session with no subscribers.

        Identity-checked so a session that gets reused before the timer fires is
        never dropped out from under a live socket.
        """
        sess = self._sessions.get(session_id)
        if sess is None or sess.subscribers:
            return
        if sess.evict_task and not sess.evict_task.done():
            sess.evict_task.cancel()

        async def _evict(target: RealtimeSession) -> None:
            try:
                await asyncio.sleep(self._grace)
            except asyncio.CancelledError:
                return
            cur = self._sessions.get(session_id)
            if cur is target and not cur.subscribers:
                self._sessions.pop(session_id, None)

        try:
            sess.evict_task = asyncio.create_task(_evict(sess))
        except RuntimeError:  # pragma: no cover - no running loop (unit context)
            self._sessions.pop(session_id, None)


#: The one process-lived registry. Module-global so it survives the scheduler's
#: per-tick service rebuilds (CLAUDE.md: cross-tick state must not live on a
#: per-tick object).
_REGISTRY = RealtimeRegistry()


def get_registry() -> RealtimeRegistry:
    return _REGISTRY
