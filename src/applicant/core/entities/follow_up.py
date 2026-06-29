from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum

from applicant.core.ids import ApplicationId, CampaignId, FollowUpId


class FollowUpTemplate(str, Enum):
    THANK_YOU = "thank_you"
    CHECK_IN = "check_in"
    REJECTION_FOLLOW_UP = "rejection_follow_up"

class FollowUpStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    SENT = "SENT"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

@dataclass(frozen=True)
class FollowUp:
    id: FollowUpId
    campaign_id: CampaignId
    application_id: ApplicationId
    template: FollowUpTemplate
    status: FollowUpStatus = FollowUpStatus.SCHEDULED
    subject: str = ""
    body: str = ""
    scheduled_at: datetime | None = None
    sent_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
