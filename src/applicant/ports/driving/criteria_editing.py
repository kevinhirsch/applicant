"""CriteriaEditing driving port (FR-CRIT-1/2/3).

Inbound port for reading and editing per-campaign search criteria. Criteria are
human-readable + UI-editable at all times (FR-CRIT-2) and mutable by both the user and
the LLM/learning (FR-CRIT-3); learned adjustments are surfaced and overridable.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from applicant.core.entities.search_criteria import SearchCriteria
from applicant.core.ids import CampaignId


@runtime_checkable
class CriteriaEditingPort(Protocol):
    """Inbound port for per-campaign criteria get/edit."""

    def get_criteria(self, campaign_id: CampaignId) -> SearchCriteria: ...

    def edit_criteria(
        self,
        campaign_id: CampaignId,
        *,
        changes: dict,
        confirm: bool = False,
        clear_learned: bool = False,
    ) -> SearchCriteria: ...

    def apply_learned_adjustment(
        self, campaign_id: CampaignId, *, adjustment: dict, rationale: str = ""
    ) -> SearchCriteria: ...
