"""CampaignService — campaign lifecycle (FR-CRIT-4). Real-ish.

Implements the CampaignManagement driving port against the storage port. MVP-1
runs a single campaign; the service is multi-ready (clone is a data op).
"""

from __future__ import annotations

from applicant.core.entities.campaign import Campaign
from applicant.core.ids import CampaignId, new_id


class CampaignService:
    """Implements the CampaignManagement driving port."""

    def __init__(self, storage) -> None:  # storage: StoragePort
        self._storage = storage

    def create_campaign(self, name: str) -> Campaign:
        campaign = Campaign(id=CampaignId(new_id()), name=name)
        self._storage.campaigns.add(campaign)
        self._storage.commit()
        return campaign

    def get_campaign(self, campaign_id: CampaignId) -> Campaign | None:
        return self._storage.campaigns.get(campaign_id)

    def list_campaigns(self) -> list[Campaign]:
        return self._storage.campaigns.list()

    def clone_campaign(self, source_id: CampaignId, name: str) -> Campaign:
        source = self._storage.campaigns.get(source_id)
        if source is None:
            raise KeyError(f"campaign not found: {source_id}")
        import dataclasses

        clone = dataclasses.replace(source, id=CampaignId(new_id()), name=name)
        self._storage.campaigns.add(clone)
        self._storage.commit()
        return clone
