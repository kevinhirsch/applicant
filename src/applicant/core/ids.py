"""Strongly-typed identifiers for domain aggregates.

Using ``NewType`` keeps ids opaque (a ``CampaignId`` is not interchangeable with a
``JobPostingId``) while remaining zero-cost ``str`` at runtime. Ids are strings so
they map cleanly onto UUID/text primary keys in the storage adapter.
"""

from __future__ import annotations

import uuid
from typing import NewType

CampaignId = NewType("CampaignId", str)
OnboardingProfileId = NewType("OnboardingProfileId", str)
AttributeId = NewType("AttributeId", str)
FieldMappingId = NewType("FieldMappingId", str)
FontId = NewType("FontId", str)
DiscoverySourceId = NewType("DiscoverySourceId", str)
JobPostingId = NewType("JobPostingId", str)
ResumeVariantId = NewType("ResumeVariantId", str)
GeneratedDocumentId = NewType("GeneratedDocumentId", str)
RevisionSessionId = NewType("RevisionSessionId", str)
ApplicationId = NewType("ApplicationId", str)
ScreenshotId = NewType("ScreenshotId", str)
DecisionId = NewType("DecisionId", str)
OutcomeEventId = NewType("OutcomeEventId", str)
AgentRunId = NewType("AgentRunId", str)
DetectionEventId = NewType("DetectionEventId", str)
ToolSettingId = NewType("ToolSettingId", str)
DormantSurfaceId = NewType("DormantSurfaceId", str)
AppConfigId = NewType("AppConfigId", str)
PendingActionId = NewType("PendingActionId", str)


def new_id() -> str:
    """Generate a fresh opaque identifier (UUID4 hex)."""
    return uuid.uuid4().hex
