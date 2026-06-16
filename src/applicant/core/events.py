"""Domain events (pure dataclasses).

Events are emitted by the core to describe things that happened, decoupled from
how adapters react (notify, persist, learn). They carry no behavior.
"""

from __future__ import annotations

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


@dataclass(frozen=True)
class ApplicationStateChanged(DomainEvent):
    """An application moved between §7 lifecycle states."""

    application_id: ApplicationId = field(default=None)  # type: ignore[assignment]
    from_state: str = ""
    to_state: str = ""


@dataclass(frozen=True)
class PendingActionRaised(DomainEvent):
    """A waiting state surfaced an item for the pending-actions portal (FR-UI-3)."""

    application_id: ApplicationId = field(default=None)  # type: ignore[assignment]
    action_kind: str = ""


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
