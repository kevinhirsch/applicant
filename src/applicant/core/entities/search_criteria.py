"""SearchCriteria entity — human-readable, UI- and LLM-mutable (FR-CRIT-1..3)."""

from __future__ import annotations

from dataclasses import dataclass, field

from applicant.core.ids import CampaignId


@dataclass(frozen=True)
class SearchCriteria:
    """Per-campaign, self-learning search criteria.

    ``human_readable`` is the always-visible, UI-editable statement (FR-CRIT-2);
    ``learned_adjustments`` records LLM/learning deltas surfaced transparently and
    overridable (FR-CRIT-3).
    """

    campaign_id: CampaignId
    human_readable: str = ""
    titles: tuple[str, ...] = ()
    locations: tuple[str, ...] = ()
    work_modes: tuple[str, ...] = ()
    salary_floor: int | None = None
    keywords: tuple[str, ...] = ()
    learned_adjustments: dict = field(default_factory=dict)
