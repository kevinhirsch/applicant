"""Domain events (pure dataclasses) + a lightweight in-process event bus.

Events are emitted by the core to describe things that happened, decoupled from
how adapters react (notify, persist, learn). They carry no behavior.

The ``DomainEventBus`` is a simple subscribe/emit channel that lets adapters
(e.g. the audit log) react to every domain event without the core importing them.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from applicant.core.ids import (
    ApplicationId,
    CampaignId,
    GeneratedDocumentId,
    JobPostingId,
)


def _now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# Event bus
# ---------------------------------------------------------------------------


class DomainEventBus:
    """In-process publish/subscribe for domain events.

    Singleton-per-process.  Adapters subscribe with ``on(EventType, handler)``
    and the core (or services that emit) call ``emit(event)``.  Handlers are
    called synchronously in the emitting thread; any exception in a handler is
    swallowed after logging so one faulty subscriber never breaks the emitter.
    """

    def __init__(self) -> None:
        self._handlers: dict[type, list[Callable[[DomainEvent], None]]] = {}

    def on(self, event_type: type, handler: Callable[[DomainEvent], None]) -> None:
        """Register ``handler`` to be called for every ``event_type`` (or its subclasses)."""
        self._handlers.setdefault(event_type, []).append(handler)

    def emit(self, event: DomainEvent) -> None:
        """Fire the event to every matching subscriber."""
        import logging as _logging

        _log = _logging.getLogger("applicant.events")
        for etype, handlers in self._handlers.items():
            if isinstance(event, etype):
                for h in handlers:
                    try:
                        h(event)
                    except Exception:
                        _log.exception("Event handler %r failed for %r", h, event)


#: The process-lived event bus.  Built once; shared across services.
event_bus = DomainEventBus()


# ---------------------------------------------------------------------------
# Domain events
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DomainEvent:
    """Base domain event."""

    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class JobDiscovered(DomainEvent):
    campaign_id: CampaignId = field(default=None)  # type: ignore[assignment]
    posting_id: JobPostingId = field(default=None)  # type: ignore[assignment]


@dataclass(frozen=True)
class ViabilityScored(DomainEvent):
    posting_id: JobPostingId = field(default=None)  # type: ignore[assignment]
    score: float = 0.0
    campaign_id: CampaignId = field(default=None)  # type: ignore[assignment]


@dataclass(frozen=True)
class ApplicationStateChanged(DomainEvent):
    """An application moved between §7 lifecycle states."""

    application_id: ApplicationId = field(default=None)  # type: ignore[assignment]
    from_state: str = ""
    to_state: str = ""
    reason: str = ""


@dataclass(frozen=True)
class PendingActionRaised(DomainEvent):
    """A waiting state surfaced an item for the pending-actions portal (FR-UI-3)."""

    application_id: ApplicationId = field(default=None)  # type: ignore[assignment]
    action_kind: str = ""
    reason: str = ""


@dataclass(frozen=True)
class MaterialApproved(DomainEvent):
    """Generated material passed the review gate (FR-RESUME-8)."""

    document_id: GeneratedDocumentId = field(default=None)  # type: ignore[assignment]


@dataclass(frozen=True)
class OutcomeRecorded(DomainEvent):
    """Submission/conversion event (FR-LOG-4, FR-LEARN-2)."""

    application_id: ApplicationId = field(default=None)  # type: ignore[assignment]
    outcome_type: str = ""
    source: str = ""
    reason: str = ""
