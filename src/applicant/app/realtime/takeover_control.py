"""Upstream ``takeover`` dispatcher (realtime-websocket.md, Phase 4).

The ``takeover`` channel's enabled upstream verbs (``input``/``start``/``stop``,
gated by :func:`applicant.core.realtime.envelope.authorize_upstream`) are **pure
transport** to the EXISTING owner-gated takeover surface — the SAME sandbox +
remote-view sub-port the HTTP ``/api/remote`` router uses. The WebSocket adds **no
new authority**: it can only do what the owner can already do over that surface,
and there is NO submit/approve path here at all (those verbs stay default-DENIED at
the envelope seam and never reach this dispatcher). Live takeover is a HUMAN driving
the browser to hand-finish; the review-before-submit stop-boundary is untouched.

Mapping (each a one-to-one call to :class:`~applicant.adapters.sandbox.takeover.
TakeoverControl`, which wraps the EXISTING owner-gated methods):

* ``takeover/start`` -> ``TakeoverControl.authorize`` (== ``POST
  /api/remote/sessions/{id}/takeover``: ``remote_view.authorize_takeover``), and
  starts streaming CDP screencast frames DOWN the ``takeover`` channel.
* ``takeover/stop``  -> ``TakeoverControl.revoke`` (``remote_view.revoke_takeover``)
  and stops the screencast.
* ``takeover/input`` -> ``TakeoverControl.send_input``: forwards ONE raw human
  mouse/keyboard event to the live browser over CDP, but ONLY while the user holds
  control (``has_takeover``). It carries no application authority.

The composition root (``container.py``) injects a ``service_factory`` yielding the
process-lived :class:`TakeoverControl` plus a ``close`` (mirroring the ``agent``
dispatcher). This module stays free of sandbox/CDP wiring so the registry seam that
calls it (``RealtimeSession.apply_upstream``) knows nothing about what it delegates to.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from applicant.core.realtime.envelope import Frame, UpstreamDecision

#: ``() -> (takeover_control, close)`` — the takeover-control handle plus a zero-arg
#: closer. Injected by the container; the dispatcher never builds the sandbox/CDP.
TakeoverControlServiceFactory = Callable[[], tuple[Any, Callable[[], None]]]

#: The verbs this dispatcher handles. It is only ever reached AFTER
#: ``authorize_upstream`` has already allowed the ``(chan, type)`` pair, so this is
#: a defensive second gate, not the authority — ``approve``/submit never arrive.
_SUPPORTED = frozenset({"input", "start", "stop"})

#: Upstream ``takeover`` dispatcher: ``(Frame) -> UpstreamDecision``.
TakeoverControlDispatcher = Callable[[Frame], UpstreamDecision]


def make_takeover_control_dispatcher(
    service_factory: TakeoverControlServiceFactory,
) -> TakeoverControlDispatcher:
    """Build the ``takeover`` upstream dispatcher over an injected service factory.

    Returns a callable the realtime registry invokes for an ALREADY-authorized
    ``takeover/input``/``start``/``stop`` frame. It resolves the target session from
    ``frame.data['session_id']`` and delegates to the matching
    :class:`TakeoverControl` method. Any failure (unknown session, the user does not
    hold control) is returned as a denied :class:`UpstreamDecision` so the endpoint
    can surface the reason back to just that socket — it never raises into the WS loop.
    """

    def dispatch(frame: Frame) -> UpstreamDecision:
        verb = frame.type
        if verb not in _SUPPORTED:  # pragma: no cover - envelope seam already gated this
            return UpstreamDecision(False, f"unsupported takeover command {verb!r}")
        data = frame.data or {}
        session_id = str(data.get("session_id") or "").strip()
        if not session_id:
            return UpstreamDecision(False, "takeover command requires a session_id")
        try:
            ctrl, close = service_factory()
        except Exception:  # pragma: no cover - defensive: never break the WS loop
            return UpstreamDecision(False, "takeover control unavailable")
        try:
            if verb == "start":
                ok, reason = ctrl.authorize(session_id)
            elif verb == "stop":
                ok, reason = ctrl.revoke(session_id)
            else:  # "input": forward ONE raw human mouse/keyboard event.
                event = data.get("event")
                if not isinstance(event, dict):
                    # Back-compat: allow the input payload to ride ``data`` directly
                    # (minus the routing key) when no nested ``event`` is given.
                    event = {k: v for k, v in data.items() if k != "session_id"}
                ok, reason = ctrl.send_input(session_id, event)
            return UpstreamDecision(bool(ok), reason or "")
        except Exception:  # pragma: no cover - defensive: a control hiccup is not fatal
            return UpstreamDecision(False, "takeover control failed")
        finally:
            try:
                close()
            except Exception:  # pragma: no cover - closing must never raise
                pass

    return dispatch
