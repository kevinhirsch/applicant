"""Scheduler tick-failure-path hardening (lens 04 #33 / #40 + DISC-1).

Three gaps this closes, all hermetic (injected clock, no real sleeps, in-memory
storage, spy collaborators):

* **#33** — ``_tick_services_factory()`` used to run BEFORE the tick's ``try:``,
  so a build failure (e.g. a bad DB connection) escaped the tick's own error
  handling entirely: ``_tick_running`` never got reset back to ``False`` and no
  metrics sample was ever recorded for that tick, unlike every other tick
  failure. The fix moves the factory call inside the ``try`` so a build failure
  is caught/recorded exactly like any other tick error, and the scheduler is
  still healthy for its next tick.
* **#40** — the ladder-advance (``_advance_ladders``) and the final metrics
  emission used to run AFTER the tick's ``try/except/finally``, so a tick that
  raised skipped both entirely (the raise propagates straight out of the
  function). The fix moves both into the ``finally`` (guarded, so a failure
  there can never itself escape or mask the tick's real exception) so a
  failing tick still advances the escalation ladder and stays observable.
* **DISC-1** — ``PostSubmissionService.send_scheduled_follow_ups`` must be
  drained every tick (not once/day, since a follow-up's due time is a real
  timestamp) and a failure sending must never break the tick. This hook
  (``Scheduler._run_follow_up_send``) already exists on this branch; these
  tests pin down that it fires every tick and is failure-isolated so a
  regression here is caught the same way as #33/#40.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.notification_service import NotificationService
from applicant.application.services.scheduler import Scheduler
from applicant.core.entities.campaign import Campaign
from applicant.core.ids import CampaignId, new_id
from applicant.observability.metrics import Metrics


def _campaign(storage):
    cid = CampaignId(new_id())
    storage.campaigns.add(Campaign(id=cid, name="C", active=True))
    return cid


class _Loop:
    def tick(self, campaign_id, now=None, **_):
        return None


class _BoomCampaignsStorage:
    """A storage stub whose ``campaigns.list()`` raises -- simulates something
    inside the tick body (other than a single guarded per-campaign step)
    blowing up, so the exception escapes the outer ``try`` in ``tick()``."""

    class _Campaigns:
        def list(self):
            raise RuntimeError("storage exploded")

    def __init__(self):
        self.campaigns = self._Campaigns()


class _AdvanceSpyNotifier:
    """A minimal NotificationPort recording every ``advance()`` call."""

    def __init__(self) -> None:
        self.advance_calls = 0

    def notify(self, notification) -> str:
        return "h"

    def expire(self, dedup_key: str) -> None:
        pass

    def advance(self, now=None) -> list:
        self.advance_calls += 1
        return ["fired-1"]


class _FollowUp:
    def __init__(self, fid="fup-1"):
        self.id = fid


class _PostSubSpy:
    """Spy standing in for ``PostSubmissionService`` -- the SEND-QUEUE entry
    point the scheduler must call every tick (DISC-1)."""

    def __init__(self, *, raises=False):
        self.send_calls: list = []
        self._raises = raises

    def send_scheduled_follow_ups(self, now=None):
        self.send_calls.append(now)
        if self._raises:
            raise RuntimeError("send queue exploded")
        return [_FollowUp()]

    # Unused by these tests but present so the scheduler's OTHER
    # post-submission steps (covered elsewhere) don't blow up if they also run
    # against this same spy.
    def run_post_submission_sweep(self, campaign_id, *, now=None):
        return {"ghosted": [], "followups_drafted": []}

    def scan_inbox_for_outcomes(self, campaign_id, **_):
        return {"scanned": 0, "matched": 0}


# --- #33: a service-build failure is caught/recorded like any other tick error, ---
# --- and the scheduler survives to its next tick -----------------------------
@pytest.mark.unit
def test_service_build_failure_is_recorded_and_scheduler_survives_next_tick():
    storage = InMemoryStorage()
    _campaign(storage)
    calls = {"n": 0}

    def factory():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("db connection refused")
        return {"storage": storage, "agent_loop": _Loop()}

    metrics = Metrics()
    sched = Scheduler(
        storage=storage,
        agent_loop=_Loop(),
        tick_services_factory=factory,
        metrics=metrics,
    )

    t0 = datetime(2026, 6, 16, 9, 0, tzinfo=UTC)
    with pytest.raises(RuntimeError):
        sched.tick(t0)

    # The tick's OWN bookkeeping ran despite the factory blowing up: the
    # running flag was reset (not stuck True forever) and this tick was
    # recorded as a failure on the metrics surface, exactly like any other
    # tick error.
    assert sched.state(t0)["running"] is False
    snap = sched.metrics_snapshot()
    assert snap["ticks_total"] == 1
    assert snap["ticks_failed"] == 1
    assert snap["last_tick_success"] is False

    # The scheduler is still healthy for the NEXT tick (the factory succeeds
    # this time).
    out = sched.tick(t0 + timedelta(minutes=1))
    assert out["tick_ok"] is True
    snap2 = sched.metrics_snapshot()
    assert snap2["ticks_total"] == 2
    assert snap2["ticks_succeeded"] == 1


# --- #40: the ladder still advances + metrics still get recorded on a raise ---
@pytest.mark.unit
def test_ladder_advance_and_metrics_still_run_when_tick_body_raises():
    notifier = _AdvanceSpyNotifier()
    notif_service = NotificationService(notifier)
    metrics = Metrics()
    sched = Scheduler(
        storage=_BoomCampaignsStorage(),
        agent_loop=_Loop(),
        notification_service=notif_service,
        metrics=metrics,
    )

    t0 = datetime(2026, 6, 16, 9, 0, tzinfo=UTC)
    with pytest.raises(RuntimeError):
        sched.tick(t0)

    # The ladder advanced even though the tick body raised before ever
    # reaching the campaign loop.
    assert notifier.advance_calls == 1
    # And the FULL metrics sample (including the ladder-fired count) was
    # still recorded for this failed tick -- not skipped because of the raise.
    snap = sched.metrics_snapshot()
    assert snap["ticks_total"] == 1
    assert snap["ticks_failed"] == 1
    assert snap["ladder_fired"] == 1


@pytest.mark.unit
def test_ladder_advance_and_metrics_run_once_per_tick_on_success_too():
    """Sanity check the fix didn't introduce a double-recording regression on
    the ordinary success path (metrics/ladder used to run exactly once after
    the try/finally; they must still run exactly once now that they live
    inside the finally)."""
    notifier = _AdvanceSpyNotifier()
    notif_service = NotificationService(notifier)
    metrics = Metrics()
    storage = InMemoryStorage()
    _campaign(storage)
    sched = Scheduler(
        storage=storage,
        agent_loop=_Loop(),
        notification_service=notif_service,
        metrics=metrics,
    )

    sched.tick(datetime(2026, 6, 16, 9, 0, tzinfo=UTC))

    assert notifier.advance_calls == 1
    snap = sched.metrics_snapshot()
    assert snap["ticks_total"] == 1
    assert snap["ticks_succeeded"] == 1


# --- DISC-1: due follow-ups are drained every tick, failure-isolated ---------
@pytest.mark.unit
def test_due_follow_ups_are_drained_every_tick():
    storage = InMemoryStorage()
    _campaign(storage)
    spy = _PostSubSpy()
    sched = Scheduler(storage=storage, agent_loop=_Loop(), post_submission_service=spy)

    t0 = datetime(2026, 6, 16, 9, 0, tzinfo=UTC)
    out1 = sched.tick(t0)
    out2 = sched.tick(t0 + timedelta(minutes=5))

    assert out1["follow_ups_sent"] == ["fup-1"]
    assert out2["follow_ups_sent"] == ["fup-1"]
    # Called every tick (not gated to once/day like the calendar-day sweeps).
    assert len(spy.send_calls) == 2


@pytest.mark.unit
def test_follow_up_send_failure_never_escapes_the_tick():
    storage = InMemoryStorage()
    _campaign(storage)
    spy = _PostSubSpy(raises=True)
    sched = Scheduler(storage=storage, agent_loop=_Loop(), post_submission_service=spy)

    out = sched.tick(datetime(2026, 6, 16, 9, 0, tzinfo=UTC))

    # The attempt happened...
    assert len(spy.send_calls) == 1
    # ...but its failure was swallowed -- it never broke the tick.
    assert out["follow_ups_sent"] == []
    assert out["tick_ok"] is True
