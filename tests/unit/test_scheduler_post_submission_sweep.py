"""Scheduler-driven post-submission lifecycle sweep (dark-engine audit B2 items
8/9/60): ``PostSubmissionService.check_ghosting`` + its new follow-up-drafting
pass (``run_post_submission_sweep``) previously had ZERO scheduler callers.

These prove, hermetically (injected clock, no real sleeps, a spy collaborator
so the scheduler's OWN orchestration is tested independently of the real
ghosting/drafting logic -- see ``tests/unit/test_post_submission_service.py``
for that), that:

* the scheduler runs the sweep EXACTLY once per campaign per UTC day;
* re-ticking the same day does NOT re-run it (per-day idempotency), and a new
  UTC day runs it again;
* it is a fast no-op when no service is wired, and when the automated-work gate
  is closed;
* a campaign whose sweep raises is logged and skipped -- the exception never
  escapes the tick, and the tick still completes (other campaigns / steps
  unaffected) -- best-effort, mirrors every sibling daily step in this module.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from applicant.adapters.storage.in_memory import InMemoryStorage
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


class _PostSubSpy:
    """Spy standing in for ``PostSubmissionService.run_post_submission_sweep``.

    Records every call (campaign id + the clock the scheduler passed in) so the
    scheduler's OWN once-per-(campaign, UTC day) gating/dedup can be asserted
    directly, independent of the real ghosting/drafting business logic.
    """

    def __init__(self, *, ghosted=None, drafted=None, raises=False):
        self.calls: list[tuple[str, datetime]] = []
        self._ghosted = list(ghosted or [])
        self._drafted = list(drafted or [])
        self._raises = raises

    def run_post_submission_sweep(self, campaign_id, *, now=None):
        self.calls.append((str(campaign_id), now))
        if self._raises:
            raise RuntimeError("post-submission storage exploded")
        return {"ghosted": list(self._ghosted), "followups_drafted": list(self._drafted)}


def _campaign(storage):
    cid = CampaignId(new_id())
    storage.campaigns.add(Campaign(id=cid, name="C", active=True))
    return cid


def _sched(storage, spy, *, gate_allowed=True):
    return Scheduler(
        storage=storage,
        agent_loop=_Loop(),
        setup_service=_Gate(allowed=gate_allowed),
        post_submission_service=spy,
    )


@pytest.mark.unit
def test_sweep_runs_once_per_campaign_per_day_and_is_idempotent_on_retick():
    storage = InMemoryStorage()
    cid = _campaign(storage)
    spy = _PostSubSpy(ghosted=["app-1"])
    sched = _sched(storage, spy)

    now = datetime(2026, 6, 16, 9, 0, tzinfo=UTC)
    out1 = sched.tick(now)
    assert out1["post_submission_sweep"] == {"ghosted": ["app-1"], "followups_drafted": []}
    assert len(spy.calls) == 1
    assert spy.calls[0][0] == str(cid)

    # Re-tick the SAME day -> no second call (per-day idempotency).
    out2 = sched.tick(now + timedelta(minutes=5))
    assert out2["post_submission_sweep"] == {"ghosted": [], "followups_drafted": []}
    assert len(spy.calls) == 1

    # A NEW UTC day runs the sweep again.
    out3 = sched.tick(now + timedelta(days=1))
    assert out3["post_submission_sweep"] == {"ghosted": ["app-1"], "followups_drafted": []}
    assert len(spy.calls) == 2


@pytest.mark.unit
def test_noop_when_no_service_wired():
    storage = InMemoryStorage()
    _campaign(storage)
    sched = Scheduler(storage=storage, agent_loop=_Loop(), setup_service=_Gate(allowed=True))

    out = sched.tick(datetime(2026, 6, 16, 9, 0, tzinfo=UTC))

    assert out["post_submission_sweep"] == {"ghosted": [], "followups_drafted": []}
    assert out["tick_ok"] is True


@pytest.mark.unit
def test_noop_when_gate_closed():
    storage = InMemoryStorage()
    _campaign(storage)
    spy = _PostSubSpy(ghosted=["app-1"])
    sched = _sched(storage, spy, gate_allowed=False)

    out = sched.tick(datetime(2026, 6, 16, 9, 0, tzinfo=UTC))

    assert out["post_submission_sweep"] == {"ghosted": [], "followups_drafted": []}
    assert spy.calls == []


@pytest.mark.unit
def test_a_broken_campaign_sweep_is_guarded_and_never_breaks_the_tick():
    storage = InMemoryStorage()
    cid = _campaign(storage)
    spy = _PostSubSpy(raises=True)
    sched = _sched(storage, spy)

    out = sched.tick(datetime(2026, 6, 16, 9, 0, tzinfo=UTC))

    # The sweep was ATTEMPTED (the day-guard marks before calling) but its
    # exception was caught -- nothing propagates, the tick still reports healthy.
    assert len(spy.calls) == 1
    assert spy.calls[0][0] == str(cid)
    assert out["post_submission_sweep"] == {"ghosted": [], "followups_drafted": []}
    assert out["tick_ok"] is True


@pytest.mark.unit
def test_multiple_campaigns_are_swept_independently():
    storage = InMemoryStorage()
    cid1 = _campaign(storage)
    cid2 = _campaign(storage)
    spy = _PostSubSpy(ghosted=["a"], drafted=["b"])
    sched = _sched(storage, spy)

    out = sched.tick(datetime(2026, 6, 16, 9, 0, tzinfo=UTC))

    swept_campaigns = {c for c, _ in spy.calls}
    assert swept_campaigns == {str(cid1), str(cid2)}
    # Aggregated across both campaigns.
    assert out["post_submission_sweep"] == {
        "ghosted": ["a", "a"],
        "followups_drafted": ["b", "b"],
    }
