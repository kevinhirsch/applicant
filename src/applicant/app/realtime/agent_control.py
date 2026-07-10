"""Upstream ``agent`` co-steer dispatcher (realtime-websocket.md, Phase 3).

The ``agent`` channel's enabled upstream verbs (``pause``/``redirect``/``approve``,
gated by :func:`applicant.core.realtime.envelope.authorize_upstream`) are **pure
transport** to the EXISTING owner-gated services — the SAME server-side methods the
HTTP surface already exposes. The WebSocket adds **no new authority**: it can only do
what the owner can already do over HTTP.

Mapping (each a one-to-one call to the existing service method):

* ``agent/pause``    -> ``AgentRunService.set_active(campaign_id, active=False)``
  (identical to ``POST /api/agent-runs/{id}/pause``).
* ``agent/redirect`` -> ``AgentRunService.configure_run(campaign_id, run_mode=…,
  throughput_target=…, schedule=…)`` (identical to ``PUT /api/agent-runs/{id}/config``):
  the operator steers/redirects the running agent by reconfiguring its run.
* ``agent/approve``  -> ``MaterialService.approve(document_id)`` (identical to
  ``POST /api/documents/{id}/approve``): the authenticated owner approves a reviewed
  material over a different transport. This is **NOT** a new authority and the engine
  STILL cannot self-authorize a final submit — ``MaterialService.approve`` is the
  IDENTICAL server-side review-before-submit gate the HTTP path calls, so it raises
  ``ReviewRequired`` (surfaced here as a denied decision) until the redline review
  surface was opened for the document, exactly as the HTTP surface returns 409. The
  socket cannot skip the review boundary; it just carries the human's approve.

The composition root (``container.py``) injects a ``service_factory`` that yields a
fresh, session-isolated ``AgentRunService`` per command (mirroring the per-request
isolation — the WS handler runs on the app loop, never on the request Session), plus
a ``close`` to release it, and an ``approval_factory`` that yields a session-isolated
``MaterialService`` the same way. This module stays free of storage/session wiring so
the registry seam that calls it (``RealtimeSession.apply_upstream``) knows nothing
about which service it delegates to.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from applicant.core.errors import InvalidInput, NotFound, ReviewRequired
from applicant.core.ids import CampaignId, GeneratedDocumentId
from applicant.core.realtime.envelope import Frame, UpstreamDecision

#: ``() -> (service, close)`` — a fresh, session-isolated service plus a zero-arg
#: closer. Injected by the container; the dispatcher never builds storage. The same
#: shape is used for both the ``AgentRunService`` (pause/redirect) and the
#: ``MaterialService`` (approve) factories.
AgentControlServiceFactory = Callable[[], tuple[Any, Callable[[], None]]]

#: The verbs this dispatcher handles. It is only ever reached AFTER
#: ``authorize_upstream`` has already allowed the ``(chan, type)`` pair, so this is a
#: defensive second gate, not the authority — a non-enabled submit verb never arrives.
_SUPPORTED = frozenset({"pause", "redirect", "approve"})

#: Upstream ``agent`` dispatcher: ``(Frame) -> UpstreamDecision``.
AgentControlDispatcher = Callable[[Frame], UpstreamDecision]


def make_agent_control_dispatcher(
    service_factory: AgentControlServiceFactory,
    approval_factory: AgentControlServiceFactory | None = None,
) -> AgentControlDispatcher:
    """Build the ``agent`` upstream dispatcher over injected service factories.

    Returns a callable the realtime registry invokes for an ALREADY-authorized
    ``agent/pause``, ``agent/redirect`` or ``agent/approve`` frame.

    * ``pause``/``redirect`` resolve the target campaign from
      ``frame.data['campaign_id']`` and delegate to the matching existing
      ``AgentRunService`` method (``service_factory``).
    * ``approve`` resolves the target material from ``frame.data['document_id']`` and
      delegates to ``MaterialService.approve`` (``approval_factory``) — the SAME
      review-gated method the HTTP approve calls, so a not-yet-reviewable document is
      refused with ``ReviewRequired`` here just as it is on HTTP. With no
      ``approval_factory`` wired (unit context) an approve frame is a clean denial,
      never an unreviewed mutation.

    Any domain error (missing campaign/document, invalid run mode, review required)
    is returned as a denied :class:`UpstreamDecision` so the endpoint can surface the
    reason back to just that socket — it never raises into the WS loop.
    """

    def _approve(data: dict[str, Any]) -> UpstreamDecision:
        # PURE TRANSPORT to the owner-gated review-before-submit gate. It does NOT
        # bypass the review boundary: MaterialService.approve raises ReviewRequired
        # until the redline surface was opened for the document (same as HTTP 409).
        if approval_factory is None:
            return UpstreamDecision(False, "agent approve unavailable")
        document_id = str(data.get("document_id") or "").strip()
        if not document_id:
            return UpstreamDecision(False, "agent approve requires a document_id")
        try:
            svc, close = approval_factory()
        except Exception:  # pragma: no cover - defensive: never break the WS loop
            return UpstreamDecision(False, "agent control unavailable")
        try:
            # SAME path as POST /api/documents/{id}/approve — the identical
            # server-side review gate; NEVER a bypass of review-before-submit.
            svc.approve(GeneratedDocumentId(document_id))
            return UpstreamDecision(True)
        except (NotFound, ReviewRequired, InvalidInput) as exc:
            return UpstreamDecision(False, str(exc))
        except Exception:  # pragma: no cover - defensive: a control hiccup is not fatal
            return UpstreamDecision(False, "agent control failed")
        finally:
            try:
                close()
            except Exception:  # pragma: no cover - closing a session must never raise
                pass

    def dispatch(frame: Frame) -> UpstreamDecision:
        verb = frame.type
        if verb not in _SUPPORTED:  # pragma: no cover - envelope seam already gated this
            return UpstreamDecision(False, f"unsupported agent command {verb!r}")
        data = frame.data or {}
        if verb == "approve":
            return _approve(data)
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
