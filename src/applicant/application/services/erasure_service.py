"""Erasure service — campaign-delete purge (#363).

A thin, named view over :class:`DataLifecycleService` (the one cohesive cascade), so
the erasure concern has a stable seam without duplicating the cross-store purge logic
(lift-and-shift: one implementation, two named entry points).
"""

from __future__ import annotations

from typing import Any

from applicant.application.services.data_lifecycle_service import DataLifecycleService
from applicant.core.ids import CampaignId


class ErasureService:
    """Purge a campaign and ALL its associated data (FR-CRIT-4, NFR-PRIV-1)."""

    def __init__(self, storage: Any, credentials: Any = None) -> None:
        self._lifecycle = DataLifecycleService(storage, credentials)

    def delete_campaign(self, campaign_id: CampaignId) -> dict:
        return self._lifecycle.delete_campaign(campaign_id)
