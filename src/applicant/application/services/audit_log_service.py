"""AuditLogService — unified action trail (FR-LOG-4, FR-OBS-2).

Subscribes to the process-lived ``DomainEventBus`` and persists one
``ActionEvent`` per emission so every engine action is captured in a single,
ordered, exportable record.

Usage: build once at startup (on the process-lived container) and call
``.start()`` to subscribe.  The service is additive and never touches the
event emitters — it listens passively.

**Per-event session isolation:** when a ``session_factory`` is provided
(production / real DB lane), each event handler opens its own session —
independent of the per-tick/per-request storage — so the audit log survives
transaction rollbacks in the main pipeline.  In the in-memory lane (no
session_factory) the shared storage is used directly.
"""

from __future__ import annotations

import logging

from applicant.core.entities.action_event import ActionEvent
from applicant.core.events import (
    ApplicationStateChanged,
    DomainEvent,
    DomainEventBus,
    JobDiscovered,
    MaterialApproved,
    OutcomeRecorded,
    PendingActionRaised,
    ViabilityScored,
    event_bus,
)
from applicant.core.ids import (
    ActionEventId,
    ApplicationId,
    CampaignId,
    new_id,
)

log = logging.getLogger(__name__)

#: Map domain event type → ``ActionEvent.action`` string.
_ACTION_MAP: dict[type[DomainEvent], str] = {
    JobDiscovered: "discovered",
    ViabilityScored: "scored",
    ApplicationStateChanged: "state_changed",
    PendingActionRaised: "pending_action",
    MaterialApproved: "material_approved",
    OutcomeRecorded: "outcome_recorded",
}


class AuditLogService:
    """Persists one ``ActionEvent`` per domain event emitted on the bus.

    When ``session_factory`` is given (real DB), every event opens a fresh
    session + ``SqlAlchemyStorage``, writes, commits, and closes — isolated
    from any in-flight tick/request transaction so the audit trail is durable
    regardless of rollbacks in the main pipeline.
    """

    def __init__(
        self,
        storage,
        *,
        session_factory=None,
        bus: DomainEventBus | None = None,
    ) -> None:
        self._storage = storage
        self._session_factory = session_factory
        self._bus = bus or event_bus

    def start(self) -> None:
        """Subscribe to domain events on the process-lived bus."""
        for etype in _ACTION_MAP:
            self._bus.on(etype, self._on_event)
        log.info("AuditLogService subscribed to %d event types", len(_ACTION_MAP))

    # -- event handler -------------------------------------------------------

    def _on_event(self, event: DomainEvent) -> None:
        """Persist one ActionEvent for the domain event.

        Opens its own session when ``session_factory`` is configured so the
        audit log write is never rolled back with the caller's transaction.
        """
        action = _ACTION_MAP.get(type(event), "unknown")
        reason = self._extract_reason(event)
        context = self._extract_context(event)

        app_id = self._get_application_id(event)
        campaign_id = self._get_campaign_id(event, app_id)

        ae = ActionEvent(
            id=ActionEventId(new_id()),
            occurred_at=event.occurred_at,
            application_id=app_id,
            campaign_id=campaign_id,
            actor="engine",
            action=action,
            reason=reason,
            context=context,
        )

        if self._session_factory is not None:
            self._persist_isolated(ae)
        else:
            self._storage.action_events.add(ae)
            self._storage.commit()

    def _persist_isolated(self, ae: ActionEvent) -> None:
        """Write the event through a fresh per-event session (real DB lane)."""
        from applicant.adapters.storage.repositories import SqlAlchemyStorage

        sess = self._session_factory()
        try:
            store = SqlAlchemyStorage(sess)
            store.action_events.add(ae)
            store.commit()
        except Exception:
            log.exception("Failed to persist audit event %s", ae.id)
        finally:
            try:
                sess.close()
            except Exception:
                pass

    # -- reason extraction ---------------------------------------------------

    @staticmethod
    def _extract_reason(event: DomainEvent) -> str:
        """Pull the human-readable reason from the domain event when available."""
        if isinstance(event, ApplicationStateChanged):
            return event.reason or f"{event.from_state} → {event.to_state}"
        if isinstance(event, PendingActionRaised):
            return event.reason or event.action_kind
        if isinstance(event, OutcomeRecorded):
            return event.reason or f"{event.outcome_type} ({event.source})"
        if isinstance(event, ViabilityScored):
            return f"score {event.score:.2f}"
        if isinstance(event, JobDiscovered):
            return str(event.campaign_id or "")
        if isinstance(event, MaterialApproved):
            return str(event.document_id or "")
        return ""

    @staticmethod
    def _extract_context(event: DomainEvent) -> dict:
        """Capture supplementary detail from the domain event for the JSONB context."""
        if isinstance(event, ApplicationStateChanged):
            return {"from_state": event.from_state, "to_state": event.to_state}
        if isinstance(event, ViabilityScored):
            return {"score": event.score}
        if isinstance(event, OutcomeRecorded):
            return {"outcome_type": event.outcome_type, "source": event.source}
        if isinstance(event, PendingActionRaised):
            return {"action_kind": event.action_kind}
        return {}

    # -- id resolution -------------------------------------------------------

    def _get_application_id(self, event: DomainEvent) -> ApplicationId | None:
        aid = getattr(event, "application_id", None)
        if aid and str(aid):
            return ApplicationId(str(aid))
        return None

    def _get_campaign_id(
        self, event: DomainEvent, app_id: ApplicationId | None
    ) -> CampaignId | None:
        cid = getattr(event, "campaign_id", None)
        if cid and str(cid):
            return CampaignId(str(cid))

        if app_id and self._session_factory is None:
            try:
                app = self._storage.applications.get(app_id)
                if app:
                    return app.campaign_id
            except Exception:
                pass
        return None
