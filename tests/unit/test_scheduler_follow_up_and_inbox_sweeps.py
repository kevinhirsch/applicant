"""Scheduler-driven follow-up send queue + inbox-to-outcome scan (dark-engine
audit B2 items 7/10): ``PostSubmissionService.send_scheduled_follow_ups`` /
``schedule_follow_up`` and ``scan_inbox_for_outcomes`` previously had ZERO
scheduler callers.

Mirrors ``test_scheduler_post_submission_sweep.py``'s harness exactly: a spy
collaborator standing in for ``PostSubmissionService`` so the SCHEDULER's own
orchestration (cadence, gating, best-effort isolation) is proven independently
of the real send-queue / inbox-matching logic (covered in
``tests/unit/test_post_submission_service.py``).

These prove:

* the follow-up SEND step runs EVERY tick (not once/day, unlike the
  ghosting/drafting sweep) -- gated on automated-work, fast no-op when no
  service is wired, best-effort (an exception never escapes the tick);
* the inbox-SCAN step runs at most once per campaign per UTC day (its own
  guard, independent of the post-submission-sweep guard), with the same
  gating/best-effort/no-op behavior;
* neither step ever calls ``schedule_follow_up`` itself -- the scheduler only
  ever calls ``send_scheduled_follow_ups``/``scan_inbox_for_outcomes``, so the
  HARD SAFETY boundary (only ``approve_follow_up_draft`` schedules a
  follow-up) is enforced entirely inside ``PostSubmissionService``, never
  bypassed by the scheduler.
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


class _FollowUp:
    def __init__(self, fid="fup-1"):
        self.id = fid


class _PostSubSpy:
    """Spy standing in for the two new ``PostSubmissionService`` entry points
    the scheduler drives (send queue + inbox scan), independent of the
    existing ``run_post_submission_sweep`` spy in the sibling test module."""

    def __init__(self, *, sent=None, scan_result=None, send_raises=False, scan_raises=False):
        self.send_calls: list[datetime] = []
        self.scan_calls: list[str] = []
        self._sent = sent if sent is not None else [_FollowUp()]
        self._scan_result = scan_result if scan_result is not None else {"scanned": 1, "matched": 1}
        self._send_raises = send_raises
        self._scan_raises = scan_raises

    def send_scheduled_follow_ups(self, now=None):
        self.send_calls.append(now)
        if self._send_raises:
            raise RuntimeError("send queue exploded")
        return list(self._sent)

    def scan_inbox_for_outcomes(self, campaign_id, **_):
        self.scan_calls.append(str(campaign_id))
        if self._scan_raises:
            raise RuntimeError("inbox scan exploded")
        return dict(self._scan_result)

    # Unused by these tests but required so the scheduler's OTHER
    # post-submission sweep step (already covered elsewhere) doesn't blow up
    # if it also runs against this same spy.
    def run_post_submission_sweep(self, campaign_id, *, now=None):
        return {"ghosted": [], "followups_drafted": []}


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


# --- follow-up send queue (item 7) -----------------------------------------


@pytest.mark.unit
def test_follow_up_send_runs_every_tick_not_once_per_day():
    storage = InMemoryStorage()
    _campaign(storage)
    spy = _PostSubSpy()
    sched = _sched(storage, spy)

    now = datetime(2026, 6, 16, 9, 0, tzinfo=UTC)
    out1 = sched.tick(now)
    out2 = sched.tick(now + timedelta(minutes=5))  # SAME day, minutes later

    assert out1["follow_ups_sent"] == ["fup-1"]
    assert out2["follow_ups_sent"] == ["fup-1"]
    # Unlike the once-per-day sweeps, this ran on BOTH ticks.
    assert len(spy.send_calls) == 2
    assert spy.send_calls[0] == now
    assert spy.send_calls[1] == now + timedelta(minutes=5)


@pytest.mark.unit
def test_follow_up_send_noop_when_no_service_wired():
    storage = InMemoryStorage()
    _campaign(storage)
    sched = Scheduler(storage=storage, agent_loop=_Loop(), setup_service=_Gate(allowed=True))

    out = sched.tick(datetime(2026, 6, 16, 9, 0, tzinfo=UTC))

    assert out["follow_ups_sent"] == []
    assert out["tick_ok"] is True


@pytest.mark.unit
def test_follow_up_send_noop_when_gate_closed():
    storage = InMemoryStorage()
    _campaign(storage)
    spy = _PostSubSpy()
    sched = _sched(storage, spy, gate_allowed=False)

    out = sched.tick(datetime(2026, 6, 16, 9, 0, tzinfo=UTC))

    assert out["follow_ups_sent"] == []
    assert spy.send_calls == []


@pytest.mark.unit
def test_follow_up_send_failure_is_guarded_and_never_breaks_the_tick():
    storage = InMemoryStorage()
    _campaign(storage)
    spy = _PostSubSpy(send_raises=True)
    sched = _sched(storage, spy)

    out = sched.tick(datetime(2026, 6, 16, 9, 0, tzinfo=UTC))

    assert out["follow_ups_sent"] == []
    assert out["tick_ok"] is True
    assert len(spy.send_calls) == 1  # it WAS attempted


@pytest.mark.unit
def test_follow_up_send_never_calls_schedule_follow_up():
    """The scheduler's own driver only ever calls ``send_scheduled_follow_ups``
    -- it must never itself schedule (approve) a follow-up. A spy missing
    ``schedule_follow_up``/``approve_follow_up_draft`` entirely proves the
    scheduler never reaches for them."""
    storage = InMemoryStorage()
    _campaign(storage)
    spy = _PostSubSpy()
    assert not hasattr(spy, "schedule_follow_up")
    assert not hasattr(spy, "approve_follow_up_draft")
    sched = _sched(storage, spy)

    out = sched.tick(datetime(2026, 6, 16, 9, 0, tzinfo=UTC))

    assert out["tick_ok"] is True
    assert out["follow_ups_sent"] == ["fup-1"]


# --- inbox-to-outcome scan (item 10) ----------------------------------------


@pytest.mark.unit
def test_inbox_scan_runs_once_per_campaign_per_day_and_is_idempotent_on_retick():
    storage = InMemoryStorage()
    cid = _campaign(storage)
    spy = _PostSubSpy(scan_result={"scanned": 2, "matched": 1})
    sched = _sched(storage, spy)

    now = datetime(2026, 6, 16, 9, 0, tzinfo=UTC)
    out1 = sched.tick(now)
    assert out1["inbox_scan"] == {"scanned": 2, "matched": 1}
    assert spy.scan_calls == [str(cid)]

    # Re-tick the SAME day -> no second call (per-day idempotency).
    out2 = sched.tick(now + timedelta(minutes=5))
    assert out2["inbox_scan"] == {"scanned": 0, "matched": 0}
    assert spy.scan_calls == [str(cid)]

    # A NEW UTC day scans again.
    out3 = sched.tick(now + timedelta(days=1))
    assert out3["inbox_scan"] == {"scanned": 2, "matched": 1}
    assert spy.scan_calls == [str(cid), str(cid)]


@pytest.mark.unit
def test_inbox_scan_noop_when_no_service_wired():
    storage = InMemoryStorage()
    _campaign(storage)
    sched = Scheduler(storage=storage, agent_loop=_Loop(), setup_service=_Gate(allowed=True))

    out = sched.tick(datetime(2026, 6, 16, 9, 0, tzinfo=UTC))

    assert out["inbox_scan"] == {"scanned": 0, "matched": 0}
    assert out["tick_ok"] is True


@pytest.mark.unit
def test_inbox_scan_noop_when_gate_closed():
    storage = InMemoryStorage()
    _campaign(storage)
    spy = _PostSubSpy()
    sched = _sched(storage, spy, gate_allowed=False)

    out = sched.tick(datetime(2026, 6, 16, 9, 0, tzinfo=UTC))

    assert out["inbox_scan"] == {"scanned": 0, "matched": 0}
    assert spy.scan_calls == []


@pytest.mark.unit
def test_inbox_scan_failure_is_guarded_and_never_breaks_the_tick():
    storage = InMemoryStorage()
    cid = _campaign(storage)
    spy = _PostSubSpy(scan_raises=True)
    sched = _sched(storage, spy)

    out = sched.tick(datetime(2026, 6, 16, 9, 0, tzinfo=UTC))

    assert out["inbox_scan"] == {"scanned": 0, "matched": 0}
    assert out["tick_ok"] is True
    assert spy.scan_calls == [str(cid)]  # it WAS attempted


@pytest.mark.unit
def test_inbox_scan_and_follow_up_send_cadences_are_independent():
    """The once-per-day inbox-scan guard must not block the every-tick
    follow-up send, and vice versa -- they use SEPARATE dicts."""
    storage = InMemoryStorage()
    _campaign(storage)
    spy = _PostSubSpy()
    sched = _sched(storage, spy)

    now = datetime(2026, 6, 16, 9, 0, tzinfo=UTC)
    sched.tick(now)
    sched.tick(now + timedelta(minutes=5))

    # Follow-up send ran on both ticks; inbox scan only on the first.
    assert len(spy.send_calls) == 2
    assert len(spy.scan_calls) == 1


@pytest.mark.unit
def test_multiple_campaigns_are_scanned_independently():
    storage = InMemoryStorage()
    cid1 = _campaign(storage)
    cid2 = _campaign(storage)
    spy = _PostSubSpy(scan_result={"scanned": 1, "matched": 0})
    sched = _sched(storage, spy)

    out = sched.tick(datetime(2026, 6, 16, 9, 0, tzinfo=UTC))

    assert set(spy.scan_calls) == {str(cid1), str(cid2)}
    assert out["inbox_scan"] == {"scanned": 2, "matched": 0}
