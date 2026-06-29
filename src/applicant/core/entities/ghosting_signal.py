from __future__ import annotations
from dataclasses import dataclass, field
from datetime import UTC, datetime
from applicant.core.ids import ApplicationId, CampaignId

@dataclass(frozen=True)
class GhostingSignal:
    campaign_id: CampaignId
    application_id: ApplicationId
    sla_days: int = 14
    submission_age_days: int = 0
    detected_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    detail: dict = field(default_factory=dict)
