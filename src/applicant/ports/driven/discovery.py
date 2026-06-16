"""Discovery port (FR-DISC-1..6).

A master aggregator over easy sources (JobSpy boards) plus pluggable,
user-toggleable source adapters; SearXNG for exploratory discovery. Structured
scraping/metasearch incur **zero LLM tokens** (FR-DISC-4, NFR-TOKEN-1).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from applicant.core.entities.job_posting import JobPosting
from applicant.core.entities.search_criteria import SearchCriteria
from applicant.core.ids import CampaignId


@runtime_checkable
class DiscoveryPort(Protocol):
    """Outbound port for gathering and normalizing job postings."""

    def search(self, campaign_id: CampaignId, criteria: SearchCriteria) -> list[JobPosting]:
        """Aggregate postings matching ``criteria`` across enabled sources (FR-DISC-2/3)."""
        ...

    def available_sources(self) -> list[str]:
        """Return the keys of all pluggable sources (toggled per campaign)."""
        ...
