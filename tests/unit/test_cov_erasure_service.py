from __future__ import annotations

from typing import Any

import pytest

from applicant.application.services.erasure_service import ErasureService
from applicant.core.ids import CampaignId


@pytest.fixture(autouse=True)
def _clear_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    pass  # signal convention


class _FakeDataLifecycleService:
    def __init__(self, storage: Any, credentials: Any = None) -> None:
        self.storage = storage
        self.credentials = credentials
        self.last_campaign_id: CampaignId | None = None

    def delete_campaign(self, campaign_id: CampaignId) -> dict:
        self.last_campaign_id = campaign_id
        return {"status": "purged", "campaign_id": campaign_id}


class TestErasureService:
    """Unit tests for ErasureService — campaign-delete thin wrapper."""

    @pytest.mark.unit
    def test_delete_campaign_forwards_to_lifecycle(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """delete_campaign must forward campaign_id to DataLifecycleService and
        return the lifecycle result unchanged."""
        fake = _FakeDataLifecycleService(storage={})
        monkeypatch.setattr(
            "applicant.application.services.erasure_service.DataLifecycleService",
            lambda storage, credentials=None: fake,
        )

        service = ErasureService(storage={})
        campaign_id: CampaignId = CampaignId("test-campaign-001")
        result = service.delete_campaign(campaign_id)

        assert fake.last_campaign_id == campaign_id
        assert result == {"status": "purged", "campaign_id": campaign_id}
