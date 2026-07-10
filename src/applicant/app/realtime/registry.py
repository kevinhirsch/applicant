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

    __slots__ = (
        "session_id",
        "channels",
        "subscribers",
        "presence",
        "evict_task",
        "agent_control",
        "takeover_control",
    )

    def __init__(
        self, session_id: str, agent_control: Any = None, takeover_control: Any = None
    ) -> None:
        self.session_id = session_id
        # chan -> ordered list of frame dicts; a frame's ``seq`` == its index, so
        # the buffer is both the replay log and the seq authority for the channel.
        self.channels: dict[str, list[dict[str, Any]]] = {}
        self.subscribers: set[asyncio.Queue] = set()
        self.presence: set[str] = set()
        self.evict_task: asyncio.Task | None = None
        # Phase 3 ``agent`` co-steer: ``(Frame) -> UpstreamDecision`` delegating an
        # ALREADY-authorized ``pause``/``redirect`` to the EXISTING owner-gated
        # ``AgentRunService`` (injected by the container via the registry). ``None``
        # (unit context / not yet bound) => an authorized agent command is a no-op,
        # never a mutation. It carries NO authority of its own — the safety decision
        # already happened at ``authorize_upstream`` before this is ever consulted.
        self.agent_control = agent_control
        # Phase 4 ``takeover``: ``(Frame) -> UpstreamDecision`` delegating an
        # ALREADY-authorized ``input``/``start``/``stop`` to the EXISTING owner-gated
        # takeover surface (the same remote-view takeover the HTTP ``/api/remote``
        # path uses). ``None`` (unit context / not bound) => an authorized takeover
        # command is a clean no-op, never a mutation, and never a submit — there is
        # no submit/approve verb on this channel at all.
        self.takeover_control = takeover_control

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

        Phase 1 implements the ``presence`` verbs; Phase 3 adds the ``agent``
        co-steer verbs (``pause``/``redirect``), delegated to the injected
        agent-control handler that calls the EXISTING owner-gated
        ``AgentRunService``. A denied frame mutates NOTHING and returns the
        decision so the endpoint can send the reason back to just that socket.
        This is the single server-side choke point later phases extend — never
        gate it on a caller-supplied flag.
        """
        decision = authorize_upstream(frame.chan, frame.type)
        if not decision.allowed:
            return decision
        if frame.chan == "presence":
            self._apply_presence(frame)
            return decision
        if frame.chan == "agent":
            return self._apply_agent(frame)
        if frame.chan == "takeover":
            return self._apply_takeover(frame)
        return decision

    def _apply_agent(self, frame: Frame) -> UpstreamDecision:
        """Delegate an ALREADY-authorized ``agent`` co-steer frame (Phase 3).

        ``authorize_upstream`` has already confirmed the verb is one of the safe
        enabled set (``pause``/``redirect``); this only forwards it to the injected
        handler, which calls the EXISTING ``AgentRunService`` method — pure
        transport, no new authority. With no handler wired (unit context, or the
        registry was never bound) an authorized command is a clean no-op rather
        than a mutation, and never raises into the WS receive loop.
        """
        handler = self.agent_control
        if handler is None:
            return UpstreamDecision(True)
        try:
            outcome = handler(frame)
        except Exception:  # pragma: no cover - defensive: a handler slip is not fatal
            return UpstreamDecision(False, "agent control failed")
        return outcome if outcome is not None else UpstreamDecision(True)

    def _apply_takeover(self, frame: Frame) -> UpstreamDecision:
        """Delegate an ALREADY-authorized ``takeover`` frame (Phase 4).

        ``authorize_upstream`` has already confirmed the verb is one of the enabled
        set (``input``/``start``/``stop`` — NEVER a submit/approve verb); this only
        forwards it to the injected handler, which calls the EXISTING owner-gated
        takeover surface — pure transport, no new authority. With no handler wired
        (unit context, or the registry was never bound) an authorized command is a
        clean no-op rather than a mutation, and never raises into the WS receive loop.
        """
        handler = self.takeover_control
        if handler is None:
            return UpstreamDecision(True)
        try:
            outcome = handler(frame)
        except Exception:  # pragma: no cover - defensive: a handler slip is not fatal
            return UpstreamDecision(False, "takeover control failed")
        return outcome if outcome is not None else UpstreamDecision(True)

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
        # The app event loop the WS sockets + their subscriber queues live on.
        # Bound once at startup (lifespan) so ``publish_all`` — called from the
        # SYNC scheduler tick (a worker thread) or a threadpool request handler —
        # can hop a downstream fan-out back onto the loop thread. asyncio.Queue is
        # not thread-safe, so publishing off-loop must go through
        # ``loop.call_soon_threadsafe`` (Phase 2 notif push).
        self._loop: asyncio.AbstractEventLoop | None = None
        # Phase 3 ``agent`` co-steer handler: ``(Frame) -> UpstreamDecision``
        # delegating an authorized ``pause``/``redirect`` to the EXISTING owner-gated
        # ``AgentRunService``. Bound once at composition time (``container.py``); every
        # session created here shares it. ``None`` (unit context / not bound) keeps an
        # authorized agent command a clean no-op.
        self._agent_control: Any = None
        # Phase 4 ``takeover`` handler: ``(Frame) -> UpstreamDecision`` delegating an
        # authorized ``input``/``start``/``stop`` to the EXISTING owner-gated takeover
        # surface. Bound once at composition time; every session shares it. ``None``
        # (unit context / not bound) keeps an authorized takeover command a clean no-op.
        self._takeover_control: Any = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop | None) -> None:
        """Record the app event loop so off-loop publishers can hop onto it."""
        self._loop = loop

    def bind_agent_control(self, handler: Any) -> None:
        """Bind the ``agent`` co-steer handler (Phase 3) onto the registry.

        Refreshes every already-created session too, so binding order (this vs. a
        session opened at boot) never leaves a live session without the handler.
        The handler is pure transport to the existing ``AgentRunService`` — binding
        it adds no authority the owner does not already have over HTTP.
        """
        self._agent_control = handler
        for sess in list(self._sessions.values()):
            sess.agent_control = handler

    def bind_takeover_control(self, handler: Any) -> None:
        """Bind the ``takeover`` handler (Phase 4) onto the registry.

        Refreshes every already-created session too, so binding order never leaves a
        live session without the handler. The handler is pure transport to the
        existing owner-gated takeover surface — binding it adds no authority the
        owner does not already have over HTTP, and no submit/approve path exists.
        """
        self._takeover_control = handler
        for sess in list(self._sessions.values()):
            sess.takeover_control = handler

    def get_or_create(self, session_id: str) -> RealtimeSession:
        sess = self._sessions.get(session_id)
        if sess is None:
            sess = RealtimeSession(
                session_id,
                agent_control=self._agent_control,
                takeover_control=self._takeover_control,
            )
            self._sessions[session_id] = sess
        return sess

    def publish_all(self, chan: str, mtype: str, data: dict[str, Any]) -> None:
        """Fan a server-originated frame to EVERY live session's ``chan`` buffer.

        The engine is single-tenant, so in practice there is one owner bridge
        session (many tabs share it); broadcasting to all live sessions reaches
        whatever bridge(s) are currently connected without the publisher needing
        to know the workspace's per-owner session id. Used by the notification +
        pending-action publish seams (Phase 2 ``notif``).

        Thread-safe: when called off the app loop (the sync scheduler tick runs in
        a worker thread; sync request handlers run in a threadpool), the actual
        buffer append + queue fan-out is marshalled back onto the loop via
        ``call_soon_threadsafe`` so no asyncio.Queue is touched cross-thread. With
        no loop bound (unit context) it publishes inline. Never raises — a
        transport hiccup must never break the service that emitted the event.
        """

        def _do() -> None:
            for sess in list(self._sessions.values()):
                try:
                    sess.publish(chan, mtype, data)
                except Exception:  # pragma: no cover - one session never breaks others
                    pass

        loop = self._loop
        if loop is None:
            _do()
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            _do()
        else:
            try:
                loop.call_soon_threadsafe(_do)
            except Exception:  # pragma: no cover - loop closing/closed during shutdown
                pass

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
