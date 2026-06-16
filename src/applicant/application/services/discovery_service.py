"""DiscoveryService (FR-DISC-*, FR-AGENT-3).

# STAGE B — owned by Phase 1; flesh out here.

Coordinates the Discovery + Embedding ports + scoring; writes JobPostings and
viability scores. Stub: returns empty results until Phase 1.
"""

from __future__ import annotations

from applicant.core.entities.job_posting import JobPosting
from applicant.core.ids import CampaignId


class DiscoveryService:
    def __init__(self, storage, discovery, embedding) -> None:
        self._storage = storage
        self._discovery = discovery
        self._embedding = embedding

    def run_discovery(self, campaign_id: CampaignId) -> list[JobPosting]:
        # STAGE B: search enabled sources, dedup via embeddings, persist.
        return []
