"""Upstream ``agent`` co-steer dispatcher (realtime-websocket.md, Phase 3).

The ``agent`` channel's enabled upstream verbs (``pause``/``redirect``, gated by
:func:`applicant.core.realtime.envelope.authorize_upstream`) are **pure transport**
to the EXISTING owner-gated ``AgentRunService`` — the SAME server-side methods the
HTTP surface (``routers/agent_runs.py``) already exposes. The WebSocket adds **no
new authority**: it can only do what the owner can already do over HTTP, and the
review-before-submit stop-boundary is untouched (``approve``/submit verbs stay
default-DENIED at the envelope seam and never reach this dispatcher).

Mapping (each a one-to-one call to the existing agent-control method):

* ``agent/pause``    -> ``AgentRunService.set_active(campaign_id, active=False)``
  (identical to ``POST /api/agent-runs/{id}/pause``).
* ``agent/redirect`` -> ``AgentRunService.configure_run(campaign_id, run_mode=…,
  throughput_target=…, schedule=…)`` (identical to ``PUT /api/agent-runs/{id}/config``):
  the operator steers/redirects the running agent by reconfiguring its run.

The composition root (``container.py``) injects a ``service_factory`` that yields a
fresh, session-isolated ``AgentRunService`` per command (mirroring the per-request
isolation — the WS handler runs on the app loop, never on the request Session), plus
a ``close`` to release it. This module stays free of storage/session wiring so the
registry seam that calls it (``RealtimeSession.apply_upstream``) knows nothing about
which service it delegates to.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from applicant.core.errors import InvalidInput, NotFound
from applicant.core.ids import CampaignId
from applicant.core.realtime.envelope import Frame, UpstreamDecision

#: ``() -> (agent_run_service, close)`` — a fresh, session-isolated service plus a
#: zero-arg closer. Injected by the container; the dispatcher never builds storage.
AgentControlServiceFactory = Callable[[], tuple[Any, Callable[[], None]]]

#: The verbs this dispatcher handles. It is only ever reached AFTER
#: ``authorize_upstream`` has already allowed the ``(chan, type)`` pair, so this is
#: a defensive second gate, not the authority — ``approve``/submit never arrive.
_SUPPORTED = frozenset({"pause", "redirect"})

#: Upstream ``agent`` dispatcher: ``(Frame) -> UpstreamDecision``.
AgentControlDispatcher = Callable[[Frame], UpstreamDecision]


def make_agent_control_dispatcher(
    service_factory: AgentControlServiceFactory,
) -> AgentControlDispatcher:
    """Build the ``agent`` upstream dispatcher over an injected service factory.

    Returns a callable the realtime registry invokes for an ALREADY-authorized
    ``agent/pause`` or ``agent/redirect`` frame. It resolves the target campaign
    from ``frame.data['campaign_id']`` and delegates to the matching existing
    ``AgentRunService`` method. Any domain error (missing campaign, invalid run
    mode) is returned as a denied :class:`UpstreamDecision` so the endpoint can
    surface the reason back to just that socket — it never raises into the WS loop.
    """

    def dispatch(frame: Frame) -> UpstreamDecision:
        verb = frame.type
        if verb not in _SUPPORTED:  # pragma: no cover - envelope seam already gated this
            return UpstreamDecision(False, f"unsupported agent command {verb!r}")
        data = frame.data or {}
        campaign_id = str(data.get("campaign_id") or "").strip()
        if not campaign_id:
            return UpstreamDecision(False, "agent command requires a campaign_id")
        try:
            svc, close = service_factory()
        except Exception:  # pragma: no cover - defensive: never break the WS loop
            return UpstreamDecision(False, "agent control unavailable")
        try:
            cid = CampaignId(campaign_id)
            if verb == "pause":
                # SAME path as POST /api/agent-runs/{id}/pause.
                svc.set_active(cid, False)
            else:  # "redirect": SAME path as PUT /api/agent-runs/{id}/config.
                schedule = data.get("schedule")
                svc.configure_run(
                    cid,
                    run_mode=data.get("run_mode"),
                    throughput_target=data.get("throughput_target"),
                    schedule=schedule if isinstance(schedule, dict) else None,
                )
            return UpstreamDecision(True)
        except (NotFound, InvalidInput) as exc:
            return UpstreamDecision(False, str(exc))
        except Exception:  # pragma: no cover - defensive: a control hiccup is not fatal
            return UpstreamDecision(False, "agent control failed")
        finally:
            try:
                close()
            except Exception:  # pragma: no cover - closing a session must never raise
                pass

    return dispatch
