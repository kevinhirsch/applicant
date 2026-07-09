"""Realtime transport domain rules (pure, no IO).

The frame envelope + the server-side upstream-command authorization seam that
every phase of the WebSocket bridge validates against. Kept in ``core`` (no
outward imports) so the safety decision — *may this upstream command run?* — is
derived from the frame's own ``(chan, type)`` and NEVER from a caller-supplied
flag, exactly like the rest of the safety core.
"""

from applicant.core.realtime.envelope import (
    CONTROL_CHANNEL,
    FEATURE_CHANNELS,
    Frame,
    UpstreamDecision,
    authorize_upstream,
    control_frame,
    parse_frame,
)

__all__ = [
    "CONTROL_CHANNEL",
    "FEATURE_CHANNELS",
    "Frame",
    "UpstreamDecision",
    "authorize_upstream",
    "control_frame",
    "parse_frame",
]
