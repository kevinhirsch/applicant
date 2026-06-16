"""JobSpy + SearXNG discovery adapter (FR-DISC-*).

# STAGE B — owned by Phase 1; flesh out here.

JobSpy master aggregator over easy boards + SearXNG exploratory discovery.
Structured scraping incurs zero LLM tokens (FR-DISC-4, NFR-TOKEN-1).
"""

from __future__ import annotations

from applicant.core.entities.job_posting import JobPosting
from applicant.core.entities.search_criteria import SearchCriteria
from applicant.core.ids import CampaignId


class JobSpySearxngDiscovery:
    """DiscoveryPort adapter (stub returning no postings until Phase 1)."""

    def search(self, campaign_id: CampaignId, criteria: SearchCriteria) -> list[JobPosting]:
        # STAGE B: aggregate JobSpy boards + SearXNG, normalize (FR-DISC-2/3).
        return []

    def available_sources(self) -> list[str]:
        return ["jobspy", "searxng"]
