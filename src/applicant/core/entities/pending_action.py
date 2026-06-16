"""PendingAction entity — anything awaiting user input (FR-UI-3).

Materialized for the pending-actions portal: digest approvals, document reviews,
soft errors, agent questions, final-submit approvals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from applicant.core.ids import ApplicationId, CampaignId, PendingActionId


@dataclass(frozen=True)
class PendingAction:
    """An item awaiting user input, surfaced in the portal."""

    id: PendingActionId
    campaign_id: CampaignId
    kind: str  # e.g. "digest_approval", "material_review", "missing_attr", "final_approval"
    title: str
    application_id: ApplicationId | None = None
    payload: dict = field(default_factory=dict)
    resolved: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
