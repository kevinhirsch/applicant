"""CampaignService — campaign lifecycle (FR-CRIT-4). Real-ish.

Implements the CampaignManagement driving port against the storage port. MVP-1
runs a single campaign; the service is multi-ready (clone is a data op).
"""

from __future__ import annotations

import dataclasses

from applicant.core.entities.campaign import Campaign, RunMode, clamp_throughput
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
        """Update a campaign's name / run config (rename, archive, throughput, budget).

        Only the provided fields change (partial update). The throughput target is
        clamped to the safe range [1, hard cap] (FR-AGENT-1) and the exploration
        budget to [0, 1] (FR-DISC-5) in the core so a caller can never push the
        engine past its safety envelope. ``active=False`` archives the campaign
        (the scheduler skips inactive campaigns); ``active=True`` reactivates it.
        """
        campaign = self._storage.campaigns.get(campaign_id)
        if campaign is None:
            raise KeyError(f"campaign not found: {campaign_id}")
        changes: dict = {}
        if name is not None and name.strip():
            changes["name"] = name.strip()
        if run_mode is not None:
            changes["run_mode"] = RunMode(run_mode)  # raises ValueError on bad mode
        if throughput_target is not None:
            changes["throughput_target"] = clamp_throughput(throughput_target)
        if exploration_budget is not None:
            changes["exploration_budget"] = max(0.0, min(float(exploration_budget), 1.0))
        if active is not None:
            changes["active"] = bool(active)
        if not changes:
            return campaign
        updated = dataclasses.replace(campaign, **changes)
        self._storage.campaigns.add(updated)  # add() is a merge/upsert
        self._storage.commit()
        return updated

    def clone_campaign(self, source_id: CampaignId, name: str) -> Campaign:
        source = self._storage.campaigns.get(source_id)
        if source is None:
            raise KeyError(f"campaign not found: {source_id}")
        clone = dataclasses.replace(source, id=CampaignId(new_id()), name=name)
        self._storage.campaigns.add(clone)
        self._storage.commit()
        return clone
