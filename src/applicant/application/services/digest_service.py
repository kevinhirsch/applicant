"""DigestService (FR-DIG-*, FR-FB-1).

# STAGE B — owned by Phase 1; flesh out here.

Builds the daily digest and records approve/decline-with-feedback decisions.
"""

from __future__ import annotations

from applicant.core.ids import CampaignId


class DigestService:
    def __init__(self, storage, notification) -> None:
        self._storage = storage
        self._notification = notification

    def build_digest(self, campaign_id: CampaignId) -> list[dict]:
        # STAGE B: assemble rows (summary, link, work mode, score, rationale).
        return []
