"""Unit tests for the 24/7 loop's operational metrics + consecutive-failure alert.

Issue #362 (FR-OBS-2 / NFR-OPS): the scheduler MUST (1) update a metrics/heartbeat
surface on EVERY tick and (2) raise ONE operator alert through the existing
notification ladder when N consecutive ticks fail — idempotently, never spamming.

All deterministic with an injected clock + in-memory adapters; no real sleeps.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.notification_service import NotificationService
from applicant.application.services.scheduler import Scheduler
from applicant.core.entities.campaign import Campaign
from applicant.core.ids import CampaignId, new_id
from applicant.observability.metrics import (
    DEFAULT_FAILURE_ALERT_THRESHOLD,
    Metrics,
)
from applicant.ports.driven.notification import NotificationUrgency


class _RecordingNotifier:
    """A minimal NotificationPort recording every dispatched notification."""

    def __init__(self) -> None:
        self.sent: list = []

    def notify(self, notification) -> str:
        self.sent.append(notification)
        return f"h-{len(self.sent)}"

    def expire(self, dedup_key: str) -> None:
        pass

    def advance(self, now=None) -> list:
        return []


class _HealthyLoop:
    def tick(self, campaign_id, now=None, **_kw):
        return None


class _StallingLoop:
    def tick(self, campaign_id, now=None, **_kw):
        raise RuntimeError("boom")


def _campaign(storage):
    cid = CampaignId(new_id())
    storage.campaigns.add(Campaign(id=cid, name="C"))
    return cid


def _scheduler(loop, *, notifier=None, threshold=3, metrics=None):
    storage = InMemoryStorage()
    _campaign(storage)
    notif_service = NotificationService(notifier) if notifier is not None else None
    return Scheduler(
        storage=storage,
        agent_loop=loop,
        notification_service=notif_service,
        metrics=metrics or Metrics(),
        failure_alert_threshold=threshold,
    )


# --- (1) metrics / heartbeat update on every tick (FR-OBS-2) ----------------
@pytest.mark.unit
def test_each_tick_updates_metrics_and_heartbeat():
    sched = _scheduler(_HealthyLoop())
    t0 = datetime(2026, 6, 16, 9, 0, tzinfo=UTC)
    sched.tick(t0)
    snap = sched.metrics_snapshot()
    assert snap["ticks_total"] == 1
    assert snap["ticks_succeeded"] == 1
    assert snap["last_heartbeat"] == t0.isoformat()
    assert snap["last_tick_success"] is True

    t1 = t0 + timedelta(minutes=1)
    sched.tick(t1)
    snap2 = sched.metrics_snapshot()
    assert snap2["ticks_total"] == 2
    assert snap2["last_heartbeat"] == t1.isoformat()


@pytest.mark.unit
def test_state_exposes_metrics_snapshot():
    sched = _scheduler(_HealthyLoop())
    t0 = datetime(2026, 6, 16, 9, 0, tzinfo=UTC)
    sched.tick(t0)
    state = sched.state(t0)
    assert isinstance(state.get("metrics"), dict)
    assert state["metrics"]["ticks_total"] == 1


# --- (2) consecutive-failure alert through the ladder (FR-OBS-2 / NFR-OPS) ---
@pytest.mark.unit
def test_all_campaigns_failing_marks_tick_failed():
    sched = _scheduler(_StallingLoop(), notifier=_RecordingNotifier())
    out = sched.tick(datetime(2026, 6, 16, 9, 0, tzinfo=UTC))
    assert out["tick_ok"] is False
    assert sched.metrics_snapshot()["ticks_failed"] == 1


@pytest.mark.unit
def test_one_operator_alert_at_threshold_not_per_tick():
    notifier = _RecordingNotifier()
    sched = _scheduler(_StallingLoop(), notifier=notifier, threshold=3)
    base = datetime(2026, 6, 16, 9, 0, tzinfo=UTC)

    # Below threshold: no alert yet.
    sched.tick(base)
    sched.tick(base + timedelta(minutes=1))
    assert notifier.sent == []

    # At + past the threshold: exactly ONE alert despite many more failed ticks.
    for i in range(2, 7):
        sched.tick(base + timedelta(minutes=i))
    assert len(notifier.sent) == 1
    alert = notifier.sent[0]
    assert alert.urgency is NotificationUrgency.IMMEDIATE
    assert alert.dedup_key == "scheduler_stall"
    snap = sched.metrics_snapshot()
    assert snap["consecutive_failures"] >= 3
    assert snap["alerting"] is True


@pytest.mark.unit
def test_alert_rearms_after_recovery():
    notifier = _RecordingNotifier()
    metrics = Metrics(failure_alert_threshold=2)

    storage = InMemoryStorage()
    _campaign(storage)
    notif_service = NotificationService(notifier)

    # A loop we can flip between healthy and stalling.
    state = {"fail": True}

    class _ToggleLoop:
        def tick(self, campaign_id, now=None, **_kw):
            if state["fail"]:
                raise RuntimeError("boom")
            return None

    sched = Scheduler(
        storage=storage,
        agent_loop=_ToggleLoop(),
        notification_service=notif_service,
        metrics=metrics,
        failure_alert_threshold=2,
    )
    base = datetime(2026, 6, 16, 9, 0, tzinfo=UTC)
    sched.tick(base)
    sched.tick(base + timedelta(minutes=1))  # 2nd consecutive failure -> 1 alert
    assert len(notifier.sent) == 1

    # Recover: a healthy tick re-arms the alert latch and resets the streak.
    state["fail"] = False
    sched.tick(base + timedelta(minutes=2))
    assert sched.metrics_snapshot()["consecutive_failures"] == 0

    # A NEW stall alerts again (the latch re-armed).
    state["fail"] = True
    sched.tick(base + timedelta(minutes=3))
    sched.tick(base + timedelta(minutes=4))
    assert len(notifier.sent) == 2


@pytest.mark.unit
def test_default_threshold_used_when_not_overridden():
    sched = _scheduler(_StallingLoop(), notifier=_RecordingNotifier(), threshold=DEFAULT_FAILURE_ALERT_THRESHOLD)
    assert sched.metrics_snapshot()["failure_alert_threshold"] == DEFAULT_FAILURE_ALERT_THRESHOLD


@pytest.mark.unit
def test_no_notifier_still_records_metrics_without_error():
    # The alert degrades gracefully when no notification service is wired.
    sched = _scheduler(_StallingLoop(), notifier=None, threshold=2)
    base = datetime(2026, 6, 16, 9, 0, tzinfo=UTC)
    sched.tick(base)
    sched.tick(base + timedelta(minutes=1))
    snap = sched.metrics_snapshot()
    assert snap["consecutive_failures"] == 2
    assert snap["alerting"] is True
