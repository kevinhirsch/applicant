"""DigestReview driving port (FR-DIG, FR-FB-1).

Approve/decline-with-feedback digest rows; declines feed learning + criteria delta.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from applicant.core.entities.decision import Decision
from applicant.core.ids import ApplicationId, CampaignId


@runtime_checkable
class DigestReviewPort(Protocol):
    """Inbound port for the daily digest decisions."""

    def current_digest(self, campaign_id: CampaignId) -> list[dict]:
        """Return digest rows (summary, link, work mode, fit/viability, rationale)."""
        ...

    def approve(self, application_id: ApplicationId) -> Decision: ...
    def decline(self, application_id: ApplicationId, feedback_text: str) -> Decision:
        """Decline with mandatory feedback (FR-DIG-5, FR-FB-1)."""
        ...
