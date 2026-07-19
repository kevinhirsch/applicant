"""Unit coverage for the Campaigns router (AZ0-123).

Proves the wired endpoints — not just the service methods in isolation:
  (a) ``/api/campaigns`` returns 200 with an empty list initially;
  (b) ``POST /api/campaigns`` returns 201 with id/name/run_mode;
  (c) ``GET /api/campaigns`` after creation returns the created campaign;
  (d) ``DELETE /api/campaigns/{campaign_id}`` succeeds;
  (e) ``require_llm_configured`` gate returns 409 on the raw app.

Hermetic: in-memory fake service, dependency_overrides for the LLM gate.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from applicant.app.deps import (
    get_campaign_service,
    get_data_lifecycle_service,
    require_llm_configured,
)
from applicant.app.main import create_app
from applicant.core.entities.campaign import Campaign, RunMode
from applicant.core.ids import CampaignId


# ---------------------------------------------------------------------------
# Fake services
# ---------------------------------------------------------------------------

class FakeCampaignService:
    """In-memory campaign store that mirrors CampaignService's public surface."""

    def __init__(self) -> None:
        self._campaigns: dict[str, Campaign] = {}

    def create_campaign(self, name: str) -> Campaign:
        from applicant.core.ids import new_id

        c = Campaign(id=CampaignId(new_id()), name=name)
        self._campaigns[c.id] = c
        return c

    def list_campaigns(self) -> list[Campaign]:
        from applicant.core.ids import SYSTEM_CAMPAIGN_ID

        return [c for c in self._campaigns.values() if c.id != SYSTEM_CAMPAIGN_ID]

    def get_campaign(self, campaign_id: CampaignId) -> Campaign | None:
        return self._campaigns.get(campaign_id)

    def update_campaign(self, campaign_id: CampaignId, **kwargs) -> Campaign:
        import dataclasses

        c = self._campaigns.get(campaign_id)
        if c is None:
            raise KeyError(f"campaign not found: {campaign_id}")
        updated = dataclasses.replace(c, **{k: v for k, v in kwargs.items() if v is not None})
        self._campaigns[campaign_id] = updated
        return updated

    def clone_campaign(self, source_id: CampaignId, name: str) -> Campaign:
        import dataclasses

        from applicant.core.ids import new_id

        source = self._campaigns.get(source_id)
        if source is None:
            raise KeyError(f"campaign not found: {source_id}")
        clone = dataclasses.replace(source, id=CampaignId(new_id()), name=name)
        self._campaigns[clone.id] = clone
        return clone


class FakeDataLifecycleService:
    """In-memory lifecycle service that removes campaigns from the fake store."""

    def __init__(self, campaign_service: FakeCampaignService) -> None:
        self._cs: FakeCampaignService | None = campaign_service

    def delete_campaign(self, campaign_id: CampaignId) -> dict:
        if self._cs is not None:
            self._cs._campaigns.pop(campaign_id, None)
        return {"purged": True, "applications": 0, "documents": 0, "screenshots": 0}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _no_op_parallel_safety() -> None:
    """xdist parallel-safety marker — no cache to clear here."""
    pass


@pytest.fixture
def fake_campaign_service() -> FakeCampaignService:
    return FakeCampaignService()


@pytest.fixture
def fake_lifecycle_service(
    fake_campaign_service: FakeCampaignService,
) -> FakeDataLifecycleService:
    return FakeDataLifecycleService(fake_campaign_service)


@pytest.fixture
def app(
    fake_campaign_service: FakeCampaignService,
    fake_lifecycle_service: FakeDataLifecycleService,
) -> FastAPI:
    """Boot the app with the LLM gate and all service deps overridden."""
    app = create_app()
    app.dependency_overrides[require_llm_configured] = lambda: None
    app.dependency_overrides[get_campaign_service] = lambda: fake_campaign_service
    app.dependency_overrides[get_data_lifecycle_service] = lambda: fake_lifecycle_service
    return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


# ---------------------------------------------------------------------------
# Happy-path reachability tests
# ---------------------------------------------------------------------------


class TestCampaignsRouterReachability:
    """Endpoints are reachable and return expected shapes on the gated app."""

    def test_list_campaigns_returns_empty_list(self, client: TestClient) -> None:
        r = client.get("/api/campaigns")
        assert r.status_code == 200
        assert r.json() == []

    def test_create_campaign_returns_201_with_fields(self, client: TestClient) -> None:
        r = client.post("/api/campaigns", json={"name": "Test Campaign"})
        assert r.status_code == 201
        body = r.json()
        assert "id" in body
        assert body["name"] == "Test Campaign"
        assert body["run_mode"] == RunMode.CONTINUOUS.value

    def test_list_campaigns_returns_created_campaign(self, client: TestClient) -> None:
        # Create one campaign first.
        create = client.post("/api/campaigns", json={"name": "My Campaign"})
        assert create.status_code == 201
        created = create.json()

        r = client.get("/api/campaigns")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        assert data[0]["id"] == created["id"]
        assert data[0]["name"] == "My Campaign"

    def test_delete_campaign_returns_success(self, client: TestClient) -> None:
        # Create a campaign first.
        create = client.post("/api/campaigns", json={"name": "To Delete"})
        assert create.status_code == 201
        cid = create.json()["id"]

        # Delete it.
        r = client.delete(f"/api/campaigns/{cid}")
        assert r.status_code == 200
        body = r.json()
        assert body["deleted"] is True

        # Verify it is gone.
        r2 = client.get("/api/campaigns")
        assert r2.json() == []


# ---------------------------------------------------------------------------
# LLM gate — 409 without configuration
# ---------------------------------------------------------------------------


class TestCampaignsRouterLlmGate:
    """The router-level require_llm_configured gate returns 409 when no override is set."""

    def test_list_campaigns_returns_409_when_no_llm(self) -> None:
        """Raw app (no dependency override) should return 409 for the gated endpoint."""
        raw = create_app()
        c = TestClient(raw)
        r = c.get("/api/campaigns")
        assert r.status_code == 409

    def test_create_campaign_returns_409_when_no_llm(self) -> None:
        raw = create_app()
        c = TestClient(raw)
        r = c.post("/api/campaigns", json={"name": "X"})
        assert r.status_code == 409

    def test_delete_campaign_returns_409_when_no_llm(self) -> None:
        raw = create_app()
        c = TestClient(raw)
        r = c.delete("/api/campaigns/fake-id")
        assert r.status_code == 409
