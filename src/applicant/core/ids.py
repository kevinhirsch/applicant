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
# G16: Post-submission lifecycle identifiers.
SubmissionSnapshotId = NewType("SubmissionSnapshotId", str)
FollowUpId = NewType("FollowUpId", str)
PortfolioAttachmentId = NewType("PortfolioAttachmentId", str)
RejectionSignalId = NewType("RejectionSignalId", str)
# Audit log: append-only action trail.
ActionEventId = NewType("ActionEventId", str)
# Product-gaps backlog #20: reusable screening-answer library entries.
ScreeningAnswerLibraryEntryId = NewType("ScreeningAnswerLibraryEntryId", str)


#: Reserved sentinel campaign that scopes instance-level secrets (LLM keys, sandbox
#: tokens) in the credential store, whose ``campaign_id`` is a non-null FK to
#: ``campaigns``. Seeded (inactive) at startup on a real DB; excluded from campaign
#: listings so it never surfaces as a real campaign.
SYSTEM_CAMPAIGN_ID = "__system__"


def validate_id(value: str) -> str:
    """Validate an ID string: reject empty, NUL bytes, and path-traversal patterns.

    Returns the validated string on success, raises ValueError on failure.
    Use as a FastAPI Depends or a manual guard on path-parameter values.
    """
    if not value or not value.strip():
        raise ValueError("ID must not be empty")
    if "\x00" in value:
        raise ValueError("ID must not contain NUL bytes")
    # Reject path-traversal patterns: ../, ..\, or bare .. at start
    normalized = value.replace("\\", "/")
    if normalized.startswith("..") or "/../" in normalized or "/.." == normalized:
        raise ValueError("ID must not contain path-traversal sequences")
    # Reject absolute-path-looking values
    if normalized.startswith("/") or normalized.startswith("\\"):
        raise ValueError("ID must not be an absolute path")
    return value


def assert_valid_id(value: str) -> str:
    """Alias for validate_id — raises ValueError on invalid IDs."""
    return validate_id(value)


def new_id() -> str:
    """Generate a fresh opaque identifier (UUID4 hex)."""
    return uuid.uuid4().hex
