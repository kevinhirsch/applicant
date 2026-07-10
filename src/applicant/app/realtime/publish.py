"""Publish seam for the ``notif`` channel (realtime-websocket.md, Phase 2).

The notification + pending-action services fan a downstream ``notif`` frame over
the realtime registry whenever something the user is watching changes, so the
front-door can **retire its Portal/bell poll** (keeping the poll as the fallback,
an honesty invariant — no silent dead UI).

Those services live in the ``application`` layer and MUST NOT import ``app`` (the
hexagonal import contract), so the composition root (``container.py``) injects the
callable this factory builds — a thin, layer-crossing closure over the
process-lived registry. ``notif`` is a **BE→FE** channel: this only pushes DOWN;
it never authorizes an upstream command (the review-before-submit stop-boundary is
untouched — the ``notif`` channel is upstream-denied by ``authorize_upstream``).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from applicant.app.realtime.registry import get_registry

#: The injected publisher's type: ``(message_type, payload) -> None``.
NotifPublisher = Callable[[str, dict[str, Any]], None]

#: The injected ``agent``-event publisher's type (same shape as ``NotifPublisher``).
AgentPublisher = Callable[[str, dict[str, Any]], None]


def make_notif_publisher() -> NotifPublisher:
    """Build the ``notif`` publisher the notification + pending-action services call.

    Broadcasts to every live session (single-tenant engine → the one owner bridge)
    and never raises — a transport hiccup must never break the service that emitted
    the event.
    """

    def _publish(mtype: str, data: dict[str, Any]) -> None:
        try:
            get_registry().publish_all("notif", mtype, data)
        except Exception:  # pragma: no cover - transport must never break the caller
            pass

    return _publish


def make_agent_publisher() -> AgentPublisher:
    """Build the ``agent`` publisher the agent-run service calls (Phase 3, BE→FE).

    Fans a downstream ``agent`` frame over the realtime registry whenever a live
    agent run is recorded, so the operator's tabs see a running agent's progress in
    realtime and a reconnecting tab replays the per-channel buffer then goes live
    (the SAME replay mechanic lifted from ``agent_runs.py``). This is DOWNSTREAM
    surfacing ONLY: it never authorizes an upstream command — the ``agent`` co-steer
    verbs are gated separately at ``authorize_upstream`` (default-deny, ``approve``
    off). Broadcasts to every live session and never raises — a transport hiccup
    must never break a scheduler tick that emitted the event.
    """

    def _publish(mtype: str, data: dict[str, Any]) -> None:
        try:
            get_registry().publish_all("agent", mtype, data)
        except Exception:  # pragma: no cover - transport must never break the caller
            pass

    return _publish
