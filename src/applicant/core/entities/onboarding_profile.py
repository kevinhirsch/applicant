"""OnboardingProfile entity — resumable Workday-ready intake (FR-ONBOARD-*)."""

from __future__ import annotations

from dataclasses import dataclass, field

from applicant.core.ids import CampaignId, OnboardingProfileId


@dataclass(frozen=True)
class OnboardingProfile:
    """Resumable comprehensive intake; completion gates automated work (FR-ONBOARD-2).

    ``wizard_state`` persists the resumable interview; ``intake`` holds the full
    Workday-ready profile (identity, work-auth, history, education, EEO, etc.).
    """

    id: OnboardingProfileId
    campaign_id: CampaignId
    completion_flag: bool = False  # gate
    wizard_state: dict = field(default_factory=dict)
    intake: dict = field(default_factory=dict)
