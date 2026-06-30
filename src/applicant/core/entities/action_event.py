"""ActionEvent entity — append-only audit log record (FR-LOG-4, FR-OBS-2).

One row per action the engine takes (discovered, scored, applied, prefilled,
submitted, skipped, approved, declined, …), in sequence, with the why.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from applicant.core.ids import ActionEventId, ApplicationId, CampaignId


@dataclass(frozen=True)
class ActionEvent:
    """A single action in the unified audit trail."""

    id: ActionEventId
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    application_id: ApplicationId | None = None
    campaign_id: CampaignId | None = None
    actor: str = "engine"  # "engine" | "user"
    action: str = ""  # discovered|scored|applied|prefilled|submitted|skipped|approved|declined|...
    reason: str = ""  # human-readable rationale
    context: dict = field(default_factory=dict)  # JSON-serialisable supplementary data
