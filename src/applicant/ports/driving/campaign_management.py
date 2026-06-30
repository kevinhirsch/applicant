"""CampaignManagement driving port (FR-CRIT-4).

Create/configure campaigns (clone-ready for multi-campaign). MVP-1 runs a single
campaign; the port is multi-ready.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from applicant.core.entities.campaign import Campaign
from applicant.core.ids import CampaignId


@runtime_checkable
class CampaignManagementPort(Protocol):
    """Inbound port for campaign lifecycle operations."""

    def create_campaign(self, name: str) -> Campaign: ...
    def get_campaign(self, campaign_id: CampaignId) -> Campaign | None: ...
    def list_campaigns(self) -> list[Campaign]: ...
    def update_campaign(
        self,
        campaign_id: CampaignId,
        *,
        name: str | None = None,
        run_mode: str | None = None,
        throughput_target: int | None = None,
        exploration_budget: float | None = None,
        active: bool | None = None,
    ) -> Campaign:
        """Partial-update a campaign's name / run config (rename, archive, throughput)."""
        ...
    def clone_campaign(self, source_id: CampaignId, name: str) -> Campaign:
        """Clone a campaign's setup (multi-ready; grayed until multi-campaign)."""
        ...
