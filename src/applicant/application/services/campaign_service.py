"""CampaignService — campaign lifecycle (FR-CRIT-4). Real-ish.

Implements the CampaignManagement driving port against the storage port. MVP-1
runs a single campaign; the service is multi-ready (clone is a data op).
"""

from __future__ import annotations

from applicant.core.entities.campaign import Campaign
from applicant.core.ids import CampaignId, new_id


class CampaignService:
    """Implements the CampaignManagement driving port."""

    def __init__(self, storage, criteria_service=None) -> None:  # storage: StoragePort
        self._storage = storage
        # #6: seed initial criteria at campaign creation so discovery/scoring have a
        # starting point (the campaign name as a title + human-readable statement)
        # instead of empty defaults until onboarding completes. Optional/additive.
        self._criteria_service = criteria_service

    def set_criteria_service(self, criteria_service) -> None:
        self._criteria_service = criteria_service

    def create_campaign(self, name: str) -> Campaign:
        campaign = Campaign(id=CampaignId(new_id()), name=name)
        self._storage.campaigns.add(campaign)
        self._storage.commit()
        self._seed_criteria(campaign, name)
        return campaign

    def _seed_criteria(self, campaign: Campaign, name: str) -> None:
        """Seed an initial SearchCriteria from the campaign name (#6). Best-effort."""
        if self._criteria_service is None or not name.strip():
            return
        try:
            self._criteria_service.edit_criteria(
                campaign.id,
                changes={"titles": [name.strip()], "human_readable": name.strip()},
                confirm=True,
            )
        except Exception:  # pragma: no cover - never let seeding break creation
            pass

    def get_campaign(self, campaign_id: CampaignId) -> Campaign | None:
        return self._storage.campaigns.get(campaign_id)

    def list_campaigns(self) -> list[Campaign]:
        from applicant.core.ids import SYSTEM_CAMPAIGN_ID

        # Exclude the reserved system campaign (it only scopes instance secrets).
        return [c for c in self._storage.campaigns.list() if c.id != SYSTEM_CAMPAIGN_ID]

    def clone_campaign(self, source_id: CampaignId, name: str) -> Campaign:
        source = self._storage.campaigns.get(source_id)
        if source is None:
            raise KeyError(f"campaign not found: {source_id}")
        import dataclasses

        clone = dataclasses.replace(source, id=CampaignId(new_id()), name=name)
        self._storage.campaigns.add(clone)
        self._storage.commit()
        return clone
