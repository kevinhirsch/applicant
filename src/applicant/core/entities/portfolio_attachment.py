from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum

from applicant.core.ids import ApplicationId, CampaignId, PortfolioAttachmentId


class AttachmentType(str, Enum):
    PORTFOLIO = "portfolio"
    WRITING_SAMPLE = "writing_sample"
    CERTIFICATION = "certification"
    TRANSCRIPT = "transcript"
    RECOMMENDATION = "recommendation"
    OTHER = "other"

@dataclass(frozen=True)
class PortfolioAttachment:
    id: PortfolioAttachmentId
    campaign_id: CampaignId
    application_id: ApplicationId | None = None
    attachment_type: AttachmentType = AttachmentType.OTHER
    file_name: str = ""
    storage_path: str = ""
    display_name: str = ""
    description: str = ""
    metadata: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
