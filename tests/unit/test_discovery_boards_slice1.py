"""ATS-board runtime add/remove engine slice1 unit tests."""

from __future__ import annotations

import pytest

from applicant.adapters.discovery.clients import (
    FakeAshbyClient,
    FakeGreenhouseClient,
    FakeLeverClient,
    FakeSmartRecruitersClient,
    FakeWorkdayClient,
)
from applicant.adapters.discovery.factory import (
    build_default_discovery,
    register_persisted_ats_boards,
)
from applicant.adapters.embedding.local_embedding import LocalEmbedding
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.discovery_service import DiscoveryService
from applicant.core.entities.campaign import Campaign
from applicant.core.entities.discovery_board import AtsBoard
from applicant.core.ids import AtsBoardId, CampaignId, new_id


@pytest.fixture
def storage() -> InMemoryStorage:
    return InMemoryStorage()


@pytest.fixture
def embedding() -> LocalEmbedding:
    return LocalEmbedding()


@pytest.fixture
def campaign(storage) -> Campaign:
    c = Campaign(id=CampaignId(new_id()), name="ats")
    storage.campaigns.add(c)
    storage.commit()
    return c


@pytest.mark.unit
def test_add_greenhouse_board_persists_and_registers(storage, embedding, campaign):
    svc = DiscoveryService(
        storage,
        build_default_discovery(live=False),
        embedding,
        greenhouse_client=FakeGreenhouseClient(),
    )
    result = svc.add_board(campaign.id, "greenhouse", "acme")
    assert result["ok"] is True
    assert result["source_key"] == "greenhouse:acme"
    assert result["found"] >= 1
    assert "greenhouse:acme" in svc._discovery.available_sources()
    board = storage.discovery_boards.get("greenhouse:acme")
    assert board is not None and board.enabled is True
    assert "greenhouse:acme" in svc.user_added_source_keys()
    svc.remove_board(campaign.id, "greenhouse:acme")
    assert "greenhouse:acme" not in svc._discovery.available_sources()
    assert storage.discovery_boards.get("greenhouse:acme") is None


@pytest.mark.unit
def test_add_rejects_empty_or_erroring_board(storage, embedding, campaign):
    empty = DiscoveryService(
        storage,
        build_default_discovery(live=False),
        embedding,
        greenhouse_client=FakeGreenhouseClient(jobs=[]),
    )
    with pytest.raises(ValueError, match="No live board found"):
        empty.add_board(campaign.id, "greenhouse", "nosuch")
    assert storage.discovery_boards.get("greenhouse:nosuch") is None

    class _Raising(FakeGreenhouseClient):
        def fetch_jobs(self, *, token, proxies):
            raise RuntimeError("boom")

    r = DiscoveryService(
        storage,
        build_default_discovery(live=False),
        embedding,
        greenhouse_client=_Raising(),
    )
    with pytest.raises(ValueError, match="No live board found"):
        r.add_board(campaign.id, "greenhouse", "boom")


@pytest.mark.unit
def test_startup_registers_persisted_boards_union_env_no_duplicates(
    storage, embedding, campaign
):
    storage.discovery_boards.upsert(
        AtsBoard(
            id=AtsBoardId(new_id()),
            campaign_id=campaign.id,
            provider="lever",
            token="dbco",
            source_key="lever:dbco",
            enabled=True,
        )
    )
    storage.discovery_boards.upsert(
        AtsBoard(
            id=AtsBoardId(new_id()),
            campaign_id=campaign.id,
            provider="greenhouse",
            token="acme",
            source_key="greenhouse:acme",
            enabled=True,
        )
    )
    storage.commit()
    aggregator = build_default_discovery(
        live=False, greenhouse_boards=("acme",), lever_companies=("envlever",)
    )
    register_persisted_ats_boards(
        aggregator, storage.discovery_boards.list_all(), live=False
    )
    keys = aggregator.available_sources()
    assert keys.count("greenhouse:acme") == 1
    assert "lever:dbco" in keys and "lever:envlever" in keys
    assert keys.count("lever:dbco") == 1


@pytest.mark.unit
def test_add_lever_board_persists_and_registers(storage, embedding, campaign):
    svc = DiscoveryService(
        storage,
        build_default_discovery(live=False),
        embedding,
        lever_client=FakeLeverClient(),
    )
    result = svc.add_board(campaign.id, "lever", "acme")
    assert result["ok"] is True
    assert result["source_key"] == "lever:acme"
    assert result["found"] >= 1
    board = storage.discovery_boards.get("lever:acme")
    assert board is not None and board.provider == "lever"
    assert "lever:acme" in svc.user_added_source_keys()
    svc.remove_board(campaign.id, "lever:acme")
    assert storage.discovery_boards.get("lever:acme") is None


# --- EPIC BREADTH (NFR-EXT-1): Ashby / SmartRecruiters / Workday add_board ----


@pytest.mark.unit
def test_add_ashby_board_persists_and_registers(storage, embedding, campaign):
    svc = DiscoveryService(
        storage,
        build_default_discovery(live=False),
        embedding,
        ashby_client=FakeAshbyClient(),
    )
    result = svc.add_board(campaign.id, "ashby", "acme")
    assert result["ok"] is True
    assert result["source_key"] == "ashby:acme"
    assert result["found"] >= 1
    assert "ashby:acme" in svc._discovery.available_sources()
    board = storage.discovery_boards.get("ashby:acme")
    assert board is not None and board.provider == "ashby"
    assert "ashby:acme" in svc.user_added_source_keys()
    svc.remove_board(campaign.id, "ashby:acme")
    assert "ashby:acme" not in svc._discovery.available_sources()


@pytest.mark.unit
def test_add_smartrecruiters_board_persists_and_registers(storage, embedding, campaign):
    svc = DiscoveryService(
        storage,
        build_default_discovery(live=False),
        embedding,
        smartrecruiters_client=FakeSmartRecruitersClient(),
    )
    result = svc.add_board(campaign.id, "smartrecruiters", "acme")
    assert result["ok"] is True
    assert result["source_key"] == "smartrecruiters:acme"
    assert result["found"] >= 1
    board = storage.discovery_boards.get("smartrecruiters:acme")
    assert board is not None and board.provider == "smartrecruiters"
    svc.remove_board(campaign.id, "smartrecruiters:acme")
    assert storage.discovery_boards.get("smartrecruiters:acme") is None


@pytest.mark.unit
def test_add_workday_board_persists_and_registers_with_tenant_key(
    storage, embedding, campaign
):
    """Workday's token is a compound 'host|tenant|site|Display Name' string; the
    registry/source_key uses just the tenant segment (short + readable), not the
    raw compound token (NFR-EXT-1, EPIC BREADTH)."""
    svc = DiscoveryService(
        storage,
        build_default_discovery(live=False),
        embedding,
        workday_client=FakeWorkdayClient(),
    )
    token = "acme.wd1.myworkdayjobs.com|acme|External|Acme Co"
    result = svc.add_board(campaign.id, "workday", token)
    assert result["ok"] is True
    assert result["source_key"] == "workday:acme"
    assert result["found"] >= 1
    assert "workday:acme" in svc._discovery.available_sources()
    board = storage.discovery_boards.get("workday:acme")
    assert board is not None and board.provider == "workday" and board.token == token
    svc.remove_board(campaign.id, "workday:acme")
    assert "workday:acme" not in svc._discovery.available_sources()


@pytest.mark.unit
def test_add_board_rejects_unsupported_provider(storage, embedding, campaign):
    svc = DiscoveryService(storage, build_default_discovery(live=False), embedding)
    with pytest.raises(ValueError, match="unsupported provider"):
        svc.add_board(campaign.id, "taleo", "acme")


@pytest.mark.unit
def test_add_board_rejects_rows_that_are_not_real_postings_shaped(
    storage, embedding, campaign
):
    """Kevin's rule: non-empty is not enough -- rows without a title+URL/identity
    fail the ``validate.validate_provider_rows`` gate exactly like an empty response."""

    class _JunkGreenhouseClient(FakeGreenhouseClient):
        def fetch_jobs(self, *, token, proxies):
            # Non-empty, but no row has BOTH a title and an absolute_url.
            return [{"absolute_url": "https://boards.greenhouse.test/acme/1"}, {"title": None}]

    svc = DiscoveryService(
        storage,
        build_default_discovery(live=False),
        embedding,
        greenhouse_client=_JunkGreenhouseClient(),
    )
    with pytest.raises(ValueError, match="No live board found"):
        svc.add_board(campaign.id, "greenhouse", "junk")
    assert storage.discovery_boards.get("greenhouse:junk") is None
