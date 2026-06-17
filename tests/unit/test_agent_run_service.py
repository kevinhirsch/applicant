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
def test_latest_intent_tie_breaks_on_seq_for_equal_timestamps(svc, storage, campaign):
    # FR-AGENT-7: with two runs sharing an identical timestamp, the later-recorded
    # run's intent must win (deterministic tie-break on monotonic seq).
    from applicant.core.entities.agent_run import AgentRun
    from applicant.core.ids import AgentRunId, new_id

    ts = datetime(2026, 1, 1, tzinfo=UTC)
    earlier = AgentRun(
        id=AgentRunId(new_id()),
        campaign_id=campaign.id,
        intent_sentence="earlier intent",
        timestamp=ts,
    )
    later = AgentRun(
        id=AgentRunId(new_id()),
        campaign_id=campaign.id,
        intent_sentence="later intent",
        timestamp=ts,
    )
    assert later.seq > earlier.seq
    storage.agent_runs.add(earlier)
    storage.agent_runs.add(later)
    storage.commit()
    assert svc.latest_intent(campaign.id) == "later intent"


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


# === #11: indexed seq/latest + retention ====================================
@pytest.mark.unit
def test_next_seq_uses_indexed_max_seq(svc, campaign, storage):
    """#11: start_run derives seq from AgentRunRepository.max_seq (single MAX query),
    not a full run-history scan."""
    calls = {"n": 0}

    def _max_seq(campaign_id):
        calls["n"] += 1
        return 41
    storage.agent_runs.max_seq = _max_seq

    run = svc.start_run(campaign.id, "doing a thing")
    assert run.seq == 42  # 1 + max_seq
    assert calls["n"] >= 1


@pytest.mark.unit
def test_latest_intent_uses_indexed_latest(svc, campaign, storage):
    """#11: latest_intent uses AgentRunRepository.latest (ORDER BY ... LIMIT 1)."""
    from applicant.core.entities.agent_run import AgentRun
    from applicant.core.ids import AgentRunId

    sentinel = AgentRun(
        id=AgentRunId(new_id()),
        campaign_id=campaign.id,
        intent_sentence="the newest intent",
        run_mode=campaign.run_mode,
        throughput_target=campaign.throughput_target,
    )
    storage.agent_runs.latest = lambda campaign_id: sentinel
    assert svc.latest_intent(campaign.id) == "the newest intent"


@pytest.mark.unit
def test_start_run_prunes_old_runs_via_retention(svc, campaign, storage):
    """#11: recording a run prunes runs beyond the rolling retention window."""
    pruned = {"keep": None, "calls": 0}

    def _prune(campaign_id, *, keep):
        pruned["keep"] = keep
        pruned["calls"] += 1
    storage.agent_runs.prune_old = _prune

    svc.start_run(campaign.id, "intent")
    assert pruned["calls"] == 1
    assert pruned["keep"] == AgentRunService.RUN_RETENTION
