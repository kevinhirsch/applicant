"""Frame envelope + upstream-command authorization seam (pure domain, no IO).

Both hops of the bridge (browser ⇄ workspace ⇄ engine) speak ONE envelope::

    {"chan": "presence|notif|agent|takeover|chat", "type": "...", "seq": N, "data": {...}}

* ``chan`` — logical channel; one physical socket multiplexes all channels.
* ``type`` — per-channel message type (``presence``/``join`` …).
* ``seq``  — monotonic per-``(session, chan)`` sequence for replay/ordering + gap
  detection on reconnect.
* ``data`` — JSON payload.

``authorize_upstream`` is the **safety seam**: every *upstream* command (client →
server) is classified here from its own ``(chan, type)`` and defaults to DENY.
Phase 1 only enables the ``presence`` control verbs; the consequential channels
(``agent``/``takeover``) are not wired yet and are refused, so the socket can
never become a bypass of the review-before-submit stop-boundary. Later phases
extend this seam to route each newly-enabled command through the same core rules
the HTTP path uses — the decision is NEVER taken from a caller-supplied flag.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Feature channels carried on the multiplexed socket (spec §Channels). Each has
#: its own replay buffer + monotonic ``seq`` per session.
FEATURE_CHANNELS: frozenset[str] = frozenset(
    {"presence", "notif", "agent", "takeover", "chat"}
)

#: Transport-control channel. Carries point-to-point ``hello``/``error``/``pong``
#: frames addressed to a single socket; it is NEVER buffered or replayed and its
#: ``seq`` is not part of any channel's ordered stream (sentinel ``-1``).
CONTROL_CHANNEL: str = "sys"

_ALL_CHANNELS: frozenset[str] = FEATURE_CHANNELS | {CONTROL_CHANNEL}

#: Upstream verbs enabled in THIS phase, per channel. Anything not listed here is
#: denied by :func:`authorize_upstream` (default-deny). Phase 2+ append the
#: channel verbs they wire, each gated by its own server-side rule.
_ALLOWED_UPSTREAM: dict[str, frozenset[str]] = {
    # Presence is the only round-trip proof in Phase 1: a tab announces join /
    # leave, re-syncs its live set on (re)connect, and pings to keep-alive. None
    # of these are consequential actions.
    "presence": frozenset({"join", "leave", "sync", "ping"}),
}


@dataclass(frozen=True)
class Frame:
    """One decoded envelope frame."""

    chan: str
    type: str
    seq: int = 0
    data: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"chan": self.chan, "type": self.type, "seq": self.seq, "data": self.data}


@dataclass(frozen=True)
class UpstreamDecision:
    """Result of the upstream-command authorization seam."""

    allowed: bool
    reason: str = ""


def parse_frame(raw: Any) -> Frame:
    """Validate + decode one wire object into a :class:`Frame`.

    Raises :class:`ValueError` (never leaks an internal error) when the object is
    not a well-formed envelope: unknown ``chan``, missing/empty ``type``, a
    non-int ``seq``, or a non-object ``data``. Callers surface the message back
    to the offending socket as a ``sys``/``error`` control frame — a malformed
    frame is rejected, it never mutates state.
    """
    if not isinstance(raw, dict):
        raise ValueError("frame must be a JSON object")
    chan = raw.get("chan")
    if not isinstance(chan, str) or chan not in _ALL_CHANNELS:
        raise ValueError(f"unknown channel: {chan!r}")
    mtype = raw.get("type")
    if not isinstance(mtype, str) or not mtype:
        raise ValueError("frame type must be a non-empty string")
    seq = raw.get("seq", 0)
    if isinstance(seq, bool) or not isinstance(seq, int):
        raise ValueError("frame seq must be an integer")
    data = raw.get("data", {})
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ValueError("frame data must be an object")
    return Frame(chan=chan, type=mtype, seq=seq, data=data)


def authorize_upstream(chan: str, mtype: str) -> UpstreamDecision:
    """Decide whether an *upstream* (client→server) command may run — the safety seam.

    Default-DENY: only ``(chan, type)`` pairs explicitly enabled for this phase
    are allowed. The consequential channels (``agent``/``takeover``) are not wired
    in Phase 1, so an ``agent``/``approve`` or ``takeover``/``input`` frame is
    refused here regardless of any payload flag — the review-before-submit
    stop-boundary and the pre-fill boundary still hold. Downstream
    (server-originated) frames are NOT run through this gate; only what a browser
    sends up is.
    """
    allowed = _ALLOWED_UPSTREAM.get(chan, frozenset())
    if mtype in allowed:
        return UpstreamDecision(True)
    if chan not in FEATURE_CHANNELS:
        return UpstreamDecision(False, f"channel {chan!r} does not accept upstream commands")
    return UpstreamDecision(
        False,
        f"upstream command {chan}/{mtype} is not enabled",
    )


def control_frame(mtype: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a point-to-point ``sys`` control frame (``hello``/``error``/``pong``).

    Uses the sentinel ``seq = -1`` so it is excluded from every channel's ordered
    replay stream and never deduped against a real channel sequence.
    """
    return {"chan": CONTROL_CHANNEL, "type": mtype, "seq": -1, "data": data or {}}
