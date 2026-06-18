"""Unit tests for the agent operate/observe layer (FR-AGENT-7/FR-OBS-2, NFR-ZEROCLI-1).

The 24/7 loop was startable only via a boot env var, exposed no on-demand trigger,
and reported no live heartbeat. These prove, hermetically (injected clock, in-memory
storage, no real sleeps):

* ``Scheduler.state`` reports running / last-tick / next-tick;
* ``Scheduler.run_now`` runs one tick on demand and is single-flight per campaign;
* ``AgentRunService.set_active`` pauses/resumes a campaign (so the scheduler skips it);
* ``AgentRunService.status`` summarizes config + latest intent + today's applied count.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta

import pytest

from applicant.application.services.agent_run_service import AgentRunService
from applicant.application.services.scheduler import Scheduler
from applicant.core.entities.agent_run import AgentRun
from applicant.core.entities.campaign import Campaign, RunMode
from applicant.core.errors import NotFound
from applicant.core.ids import AgentRunId, CampaignId, new_id


class _RecordingLoop:
    def __init__(self):
        self.ticked = []

    def tick(self, campaign_id, now=None):
        self.ticked.append((str(campaign_id), now))
        return {"campaign_id": str(campaign_id), "ran": True, "discovered": 3}


def _storage():
    from applicant.adapters.storage.in_memory import InMemoryStorage

    return InMemoryStorage()


def _campaign(storage, *, active=True):
    cid = CampaignId(new_id())
    storage.campaigns.add(Campaign(id=cid, name="C", active=active))
    return cid


# --- scheduler heartbeat (FR-AGENT-7/FR-OBS-2) ---------------------------------
@pytest.mark.unit
def test_state_reports_last_and_next_tick():
    storage = _storage()
    _campaign(storage)
    sched = Scheduler(storage=storage, agent_loop=_RecordingLoop(), interval_seconds=60.0)

    # Before any tick: idle, no timestamps.
    s0 = sched.state()
    assert s0["running"] is False
    assert s0["last_tick"] is None
    assert s0["next_tick"] is None
    assert s0["interval_seconds"] == 60.0

    now = datetime(2026, 6, 16, 9, 0, tzinfo=UTC)
    sched.tick(now)
    s1 = sched.state()
    assert s1["running"] is False  # tick finished
    assert s1["last_tick"] == now.isoformat()
    assert s1["next_tick"] == (now + timedelta(seconds=60)).isoformat()


@pytest.mark.unit
def test_state_running_true_during_tick():
    storage = _storage()
    _campaign(storage)
    seen = {}

    class _SlowLoop:
        def tick(self, campaign_id, now=None):
            # Capture the scheduler's running flag from inside the tick.
            seen["running"] = sched.state()["running"]
            return None

    sched = Scheduler(storage=storage, agent_loop=_SlowLoop())
    sched.tick(datetime(2026, 6, 16, 9, 0, tzinfo=UTC))
    assert seen["running"] is True
    assert sched.state()["running"] is False


# --- run-now (NFR-ZEROCLI-1) ---------------------------------------------------
@pytest.mark.unit
def test_run_now_runs_one_tick_and_returns_result():
    storage = _storage()
    cid = _campaign(storage)
    loop = _RecordingLoop()
    sched = Scheduler(storage=storage, agent_loop=loop)

    out = sched.run_now(cid)
    assert out["ran"] is True
    assert out["campaign_id"] == str(cid)
    assert out["discovered"] == 3
    assert [c for c, _ in loop.ticked] == [str(cid)]


@pytest.mark.unit
def test_run_now_is_single_flight_per_campaign():
    """A manual run never races a scheduled tick: if the campaign lock is held, the
    manual run reports ran=False rather than piling a second concurrent tick on."""
    storage = _storage()
    cid = _campaign(storage)
    sched = Scheduler(storage=storage, agent_loop=_RecordingLoop())
    # Simulate a tick already in progress for this campaign by holding its lock.
    lock = sched._campaign_lock(cid)
    assert lock.acquire(blocking=False)
    try:
        out = sched.run_now(cid)
        assert out["ran"] is False
        assert "in progress" in out["reason"]
    finally:
        lock.release()
    # Once free, a manual run proceeds.
    assert sched.run_now(cid)["ran"] is True


@pytest.mark.unit
def test_run_now_handles_loop_returning_none():
    storage = _storage()
    cid = _campaign(storage)

    class _NoneLoop:
        def tick(self, campaign_id, now=None):
            return None

    sched = Scheduler(storage=storage, agent_loop=_NoneLoop())
    out = sched.run_now(cid)
    assert out["ran"] is True
    assert out["campaign_id"] == str(cid)


# --- pause / resume (NFR-ZEROCLI-1) --------------------------------------------
@pytest.mark.unit
def test_set_active_pauses_and_scheduler_skips_paused_campaign():
    storage = _storage()
    cid = _campaign(storage)
    svc = AgentRunService(storage)
    loop = _RecordingLoop()
    sched = Scheduler(storage=storage, agent_loop=loop)

    # Active campaign ticks.
    sched.tick(datetime(2026, 6, 16, 9, 0, tzinfo=UTC))
    assert [c for c, _ in loop.ticked] == [str(cid)]

    # Pause it: persisted active=False; scheduler now skips it.
    updated = svc.set_active(cid, False)
    assert updated.active is False
    loop.ticked.clear()
    sched.tick(datetime(2026, 6, 16, 9, 1, tzinfo=UTC))
    assert loop.ticked == []

    # Resume: ticked again.
    assert svc.set_active(cid, True).active is True
    sched.tick(datetime(2026, 6, 16, 9, 2, tzinfo=UTC))
    assert [c for c, _ in loop.ticked] == [str(cid)]


@pytest.mark.unit
def test_set_active_missing_campaign_raises_notfound():
    svc = AgentRunService(_storage())
    with pytest.raises(NotFound):
        svc.set_active(CampaignId(new_id()), False)


# --- status (FR-AGENT-7/FR-OBS-2) ----------------------------------------------
@pytest.mark.unit
def test_status_summarizes_config_and_latest_intent():
    storage = _storage()
    cid = CampaignId(new_id())
    storage.campaigns.add(
        Campaign(id=cid, name="C", run_mode=RunMode.CONTINUOUS, throughput_target=12, active=True)
    )
    svc = AgentRunService(storage)
    svc.start_run(cid, "Delivered a digest of 2 viable roles.", stats={"discovered": 5})

    st = svc.status(cid)
    assert st["campaign_id"] == str(cid)
    assert st["active"] is True
    assert st["paused"] is False
    assert st["run_mode"] == "continuous"
    assert st["throughput_target"] == 12
    assert st["daily_budget"] == 12
    assert st["latest_intent"] == "Delivered a digest of 2 viable roles."
    assert st["latest_stats"] == {"discovered": 5}
    assert st["last_run_at"] is not None
    assert "applied_today" in st


@pytest.mark.unit
def test_status_paused_when_inactive():
    storage = _storage()
    cid = _campaign(storage, active=False)
    st = AgentRunService(storage).status(cid)
    assert st["active"] is False
    assert st["paused"] is True
    assert st["latest_intent"] is None


@pytest.mark.unit
def test_status_missing_campaign_raises_notfound():
    with pytest.raises(NotFound):
        AgentRunService(_storage()).status(CampaignId(new_id()))


@pytest.mark.unit
def test_status_counts_today_applied():
    """applied_today reflects pipelines started today (FR-AGENT-1 budget view)."""
    storage = _storage()
    cid = _campaign(storage)
    today = datetime(2026, 6, 16, 9, 0, tzinfo=UTC)
    # Two runs today that started 3 pipelines total (stats carry an integer count,
    # mirroring the SQL lane and the per-day throughput cap).
    storage.agent_runs.add(
        AgentRun(
            id=AgentRunId(new_id()),
            campaign_id=cid,
            intent_sentence="x",
            stats={"pipelines_started": 2},
            timestamp=today,
        )
    )
    storage.agent_runs.add(
        AgentRun(
            id=AgentRunId(new_id()),
            campaign_id=cid,
            intent_sentence="y",
            stats={"pipelines_started": 1},
            timestamp=today + timedelta(minutes=1),
        )
    )
    st = AgentRunService(storage).status(cid, now=today)
    assert st["applied_today"] == 3


@pytest.mark.unit
def test_run_now_threadsafe_lock_held_blocks_only_same_campaign():
    """run_now on campaign A is unaffected by a tick in flight on campaign B."""
    storage = _storage()
    a = _campaign(storage)
    b = _campaign(storage)
    sched = Scheduler(storage=storage, agent_loop=_RecordingLoop())
    held = threading.Lock()
    lock_b = sched._campaign_lock(b)
    assert lock_b.acquire(blocking=False)
    try:
        with held:
            assert sched.run_now(a)["ran"] is True
    finally:
        lock_b.release()
