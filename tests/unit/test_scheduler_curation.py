"""Scheduler-driven closed-loop curation nudge (FR-MIND-7/-10/-11).

These prove, hermetically (injected clock, no real sleeps), that:

* the scheduler runs the curation nudge once per UTC day, gated on the
  automated-work gate, and is a fast no-op when disabled / gated;
* re-running ticks the same day does NOT re-run the nudge, and even across a
  per-tick service REBUILD the dedupe holds because it lives in the process-lived
  ``CurationLedger`` (FR-MIND-10) — no duplicate proposals;
* the surfaced tick result reports the nudge outcome (FR-OBS-2).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from applicant.adapters.memory.in_memory import InMemoryMemoryStore, InMemorySkillStore
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.curation_service import (
    CurationLedger,
    CurationService,
    RunSummary,
)
from applicant.application.services.scheduler import Scheduler
from applicant.core.entities.campaign import Campaign
from applicant.core.ids import CampaignId, new_id


class _Loop:
    def tick(self, campaign_id, now=None, **_):
        return None


class _Gate:
    def __init__(self, allowed=True):
        self.allowed = allowed

    def is_automated_work_allowed(self) -> bool:
        return self.allowed


def _campaign(storage):
    cid = CampaignId(new_id())
    storage.campaigns.add(Campaign(id=cid, name="C", active=True))
    return cid


def _summaries(_storage, _now):
    return [
        RunSummary(
            run_id="run-1",
            campaign_id="c1",
            text="Cleared the Workday location react-select before typing the city.",
            tool_calls=7,
            succeeded=True,
            topic="acme-workday",
        )
    ]


def _curation(ledger):
    return CurationService(
        memory_store=InMemoryMemoryStore(),
        skill_store=InMemorySkillStore(),
        ledger=ledger,
    )


@pytest.mark.unit
def test_curation_runs_once_per_day_and_is_idempotent_on_retick():
    storage = InMemoryStorage()
    _campaign(storage)
    ledger = CurationLedger()
    sched = Scheduler(
        storage=storage,
        agent_loop=_Loop(),
        setup_service=_Gate(allowed=True),
        curation_service=_curation(ledger),
        curation_schedule="daily",
        run_summaries_provider=_summaries,
    )
    now = datetime(2026, 6, 16, 9, 0, tzinfo=UTC)
    out1 = sched.tick(now)
    assert out1["curation"]["ran"] is True
    assert out1["curation"]["reviewed"] == 1
    assert out1["curation"]["staged"] == 2  # one memory + one skill, staged for review

    # Re-tick the SAME day -> the nudge must NOT run again (idempotent cadence).
    out2 = sched.tick(now + timedelta(minutes=5))
    assert out2["curation"]["ran"] is False
    assert out2["curation"]["reason"] == "already_ran_today"

    # And the proposal ledger holds exactly the first run's proposals (no duplicates).
    assert len(ledger.staged) == 2
    assert "run-1" in ledger.proposed_runs


@pytest.mark.unit
def test_curation_is_noop_when_disabled():
    storage = InMemoryStorage()
    _campaign(storage)
    ledger = CurationLedger()
    sched = Scheduler(
        storage=storage,
        agent_loop=_Loop(),
        setup_service=_Gate(allowed=True),
        curation_service=_curation(ledger),
        curation_schedule="off",  # default: dormant
        run_summaries_provider=_summaries,
    )
    out = sched.tick(datetime(2026, 6, 16, 9, 0, tzinfo=UTC))
    assert out["curation"] == {"ran": False, "reason": "disabled"}
    assert ledger.staged == []


@pytest.mark.unit
def test_curation_is_noop_when_gate_closed():
    storage = InMemoryStorage()
    _campaign(storage)
    ledger = CurationLedger()
    sched = Scheduler(
        storage=storage,
        agent_loop=_Loop(),
        setup_service=_Gate(allowed=False),  # onboarding/LLM not satisfied
        curation_service=_curation(ledger),
        curation_schedule="daily",
        run_summaries_provider=_summaries,
    )
    out = sched.tick(datetime(2026, 6, 16, 9, 0, tzinfo=UTC))
    assert out["curation"] == {"ran": False, "reason": "gated"}
    assert ledger.staged == []


@pytest.mark.unit
def test_curation_state_survives_per_tick_service_rebuild():
    """The factory rebuilds the curation service each tick; the SHARED ledger keeps
    the dedupe so a second day's tick adds the new run but never re-proposes run-1."""
    storage = InMemoryStorage()
    _campaign(storage)
    ledger = CurationLedger()
    mem = InMemoryMemoryStore()
    skills = InMemorySkillStore()

    rebuilds = {"n": 0}

    def factory():
        rebuilds["n"] += 1
        # A FRESH CurationService instance each tick (like _build_tick_services), but
        # the SAME process-lived ledger + stores — that is what makes dedupe survive.
        return {
            "storage": storage,
            "agent_loop": _Loop(),
            "curation_service": CurationService(
                memory_store=mem, skill_store=skills, ledger=ledger
            ),
        }

    def day2_summaries(_storage, _now):
        # run-1 again (already proposed) + a new run-2 -> only run-2 should be new.
        return list(_summaries(_storage, _now)) + [
            RunSummary(
                run_id="run-2",
                campaign_id="c1",
                text="Acme Workday account tenant flow: use the company SSO entry.",
                tool_calls=6,
                succeeded=True,
                topic="acme-workday-account",
            )
        ]

    sched = Scheduler(
        storage=storage,
        agent_loop=_Loop(),
        setup_service=_Gate(allowed=True),
        curation_schedule="daily",
        tick_services_factory=factory,
        run_summaries_provider=_summaries,
    )
    day1 = datetime(2026, 6, 16, 9, 0, tzinfo=UTC)
    out1 = sched.tick(day1)
    assert out1["curation"]["reviewed"] == 1
    staged_after_day1 = len(ledger.staged)

    # Next UTC day: swap the provider to include run-1 (dup) + run-2 (new).
    sched._run_summaries_provider = day2_summaries
    out2 = sched.tick(day1 + timedelta(days=1))
    assert out2["curation"]["ran"] is True
    # Only run-2 is newly reviewed; run-1 is deduped by the shared ledger.
    assert out2["curation"]["reviewed"] == 1
    assert "run-1" in ledger.proposed_runs
    assert "run-2" in ledger.proposed_runs
    assert len(ledger.staged) == staged_after_day1 + 2  # run-2's memory + skill
    assert rebuilds["n"] >= 2  # the service really was rebuilt per tick
