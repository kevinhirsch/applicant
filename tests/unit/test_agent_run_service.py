"""AgentRunService unit tests (FR-AGENT-1/2/7)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.agent_run_service import AgentRunService
from applicant.core.entities.campaign import Campaign, RunMode
from applicant.core.ids import CampaignId, new_id


@pytest.fixture
def storage() -> InMemoryStorage:
    return InMemoryStorage()


@pytest.fixture
def campaign(storage) -> Campaign:
    c = Campaign(id=CampaignId(new_id()), name="c")
    storage.campaigns.add(c)
    storage.commit()
    return c


@pytest.fixture
def svc(storage) -> AgentRunService:
    return AgentRunService(storage)


@pytest.mark.unit
def test_throughput_clamped_to_hard_cap(svc, campaign):
    # FR-AGENT-1: requested 100/day is clamped to the 30/day hard cap.
    updated = svc.configure_run(campaign.id, throughput_target=100)
    assert updated.throughput_target == 30
    assert svc.daily_budget(updated) == 30


@pytest.mark.unit
def test_throughput_default_is_fifteen(campaign):
    assert campaign.throughput_target == 15


@pytest.mark.unit
def test_run_mode_is_selectable(svc, campaign):
    # FR-AGENT-2: run modes selectable per campaign.
    updated = svc.configure_run(campaign.id, run_mode="until_n_viable")
    assert updated.run_mode is RunMode.UNTIL_N_VIABLE


@pytest.mark.unit
def test_intent_sentence_recorded_and_retrievable(svc, campaign):
    # FR-AGENT-7: each run logs a single-sentence intent.
    svc.start_run(campaign.id, "Scan LinkedIn for remote backend roles next.")
    assert svc.latest_intent(campaign.id) == "Scan LinkedIn for remote backend roles next."
    assert len(svc.list_runs(campaign.id)) == 1


@pytest.mark.unit
def test_continuous_mode_always_continues(svc, campaign):
    assert svc.should_continue(campaign) is True


@pytest.mark.unit
def test_until_n_viable_stops_at_target(svc, campaign):
    c = svc.configure_run(campaign.id, run_mode="until_n_viable", schedule={"target_viable": 3})
    assert svc.should_continue(c, viable_count=2) is True
    assert svc.should_continue(c, viable_count=3) is False


@pytest.mark.unit
def test_fixed_duration_stops_after_elapsed(svc, campaign):
    c = svc.configure_run(campaign.id, run_mode="fixed_duration", schedule={"duration_minutes": 60})
    started = datetime(2026, 1, 1, tzinfo=UTC)
    assert svc.should_continue(c, started_at=started, now=started + timedelta(minutes=30)) is True
    assert svc.should_continue(c, started_at=started, now=started + timedelta(minutes=90)) is False
