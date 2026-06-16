"""JobPosting entity — normalized posting (FR-DISC-3)."""

from __future__ import annotations

from dataclasses import dataclass

from applicant.core.ids import CampaignId, JobPostingId


@dataclass(frozen=True)
class JobPosting:
    """A normalized job posting gathered by discovery."""

    id: JobPostingId
    campaign_id: CampaignId
    title: str
    company: str
    source_url: str
    location: str | None = None
    work_mode: str | None = None  # remote / hybrid / onsite
    salary: str | None = None
    description: str = ""
    source_key: str | None = None  # which discovery source yielded it
