"""JobPosting entity — normalized posting (FR-DISC-3)."""

from __future__ import annotations

from dataclasses import dataclass, field

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
    # Easy-Apply channel tag (P1-11): True when discovery detected that the
    # posting supports the board's built-in quick-apply flow (e.g. LinkedIn
    # Easy Apply). Detection only — never used to automate anything by itself.
    easy_apply: bool = False
    # Durable viability scoring (FR-DIG-4): persisted so the digest rationale survives
    # restart and is not recomputed every run. ``None`` until the posting is scored.
    viability_score: float | None = None
    rationale: dict = field(default_factory=dict)
