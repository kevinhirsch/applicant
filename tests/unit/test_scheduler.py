"""Unit tests for the Scheduler (FR-DIG-1, FR-NOTIF-2, NFR-247-1).

The scheduler is the 24/7 cadence that finally drives the engine. These prove,
with an injected clock and no real sleeps:

* ``tick`` advances each active campaign's run loop;
* the daily digest is built/delivered once per UTC day (FR-DIG-1);
* the notification escalation ladder's ``advance`` is driven so the held Discord
  push escalates to EMAIL after the configured timeout (FR-NOTIF-2) — the behavior
  that nothing called live before.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from applicant.adapters.notification.apprise_notifier import AppriseNotifier
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.notification_service import NotificationService
from applicant.application.services.scheduler import Scheduler
from applicant.core.entities.campaign import Campaign
from applicant.core.ids import CampaignId, new_id


class _Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 6, 16, 9, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def tick(self, seconds: float) -> None:
        self.now = self.now + timedelta(seconds=seconds)


class _RecordingLoop:
    def __init__(self):
        self.ticked = []

    def tick(self, campaign_id, now=None):
        self.ticked.append((str(campaign_id), now))
        return None


class _CountingDigest:
    def __init__(self):
        self.deliveries = 0

    def deliver(self, campaign_id, criteria=None):
        self.deliveries += 1
        return {"payload": {"rows": []}}


class _DeliveringLoop:
    """Models AgentLoop: delivers the digest once per (campaign, UTC day) on tick."""

    def __init__(self, digest):
        self._digest = digest
        self._sent: set[tuple[str, object]] = set()

    def tick(self, campaign_id, now=None):
        key = (str(campaign_id), now.date())
        if key not in self._sent:
            self._digest.deliver(campaign_id)
            self._sent.add(key)
        return None


def _campaign(storage, *, active=True):
    cid = CampaignId(new_id())
    storage.campaigns.add(Campaign(id=cid, name="C", active=active))
    return cid


@pytest.mark.unit
def test_tick_advances_each_active_campaign():
    storage = InMemoryStorage()
    c1 = _campaign(storage)
    c2 = _campaign(storage)
    _campaign(storage, active=False)  # inactive — never ticked
    loop = _RecordingLoop()
    sched = Scheduler(storage=storage, agent_loop=loop)
    now = datetime(2026, 6, 16, 9, 0, tzinfo=UTC)
    out = sched.tick(now)
    assert set(out["ticked"]) == {str(c1), str(c2)}
    assert {cid for cid, _ in loop.ticked} == {str(c1), str(c2)}


class _FailingLoop:
    """Raises for a configured set of campaigns; ticks the rest normally."""

    def __init__(self, fail_for: set[str]):
        self._fail_for = fail_for

    def tick(self, campaign_id, now=None):
        if str(campaign_id) in self._fail_for:
            raise RuntimeError("boom")
        return None


@pytest.mark.unit
def test_campaign_tick_failure_is_recorded_per_campaign():
    """Dark-engine audit #73: a per-campaign tick failure previously reached only
    ``log.warning`` — the metrics snapshot counts only whole-tick failures, so one
    flaky campaign inside an otherwise-healthy tick left no visible trace at all.
    ``campaign_health`` must now report the error + a running failure count, and a
    campaign that never failed reports empty (no noise)."""
    storage = InMemoryStorage()
    c1 = _campaign(storage)
    c2 = _campaign(storage)
    sched = Scheduler(storage=storage, agent_loop=_FailingLoop(fail_for={str(c1)}))
    now = datetime(2026, 6, 16, 9, 0, tzinfo=UTC)
    sched.tick(now)

    health = sched.campaign_health(c1)
    assert health["failure_count"] == 1
    assert "boom" in health["last_error"]
    assert health["last_error_at"]
    # The healthy campaign has no entry at all.
    assert sched.campaign_health(c2) == {}

    # A second failing tick bumps the running count.
    sched.tick(now + timedelta(seconds=60))
    assert sched.campaign_health(c1)["failure_count"] == 2


@pytest.mark.unit
def test_campaign_tick_overlap_skip_is_recorded_per_campaign():
    """Dark-engine audit #73: a campaign whose PRIOR tick is still running is
    skipped this interval (``campaign_tick_skipped_in_progress``) — previously
    log-only. ``campaign_health`` must report the skip + a running count."""
    storage = InMemoryStorage()
    c1 = _campaign(storage)
    loop = _RecordingLoop()
    sched = Scheduler(storage=storage, agent_loop=loop)
    now = datetime(2026, 6, 16, 9, 0, tzinfo=UTC)

    lock = sched._campaign_lock(c1)
    lock.acquire()  # simulate a still-in-flight prior tick for this campaign
    try:
        sched.tick(now)
    finally:
        lock.release()

    health = sched.campaign_health(c1)
    assert health["skipped_count"] == 1
    assert health["last_skipped_at"]
    assert loop.ticked == []  # never reached the loop this tick


@pytest.mark.unit
def test_daily_digest_delivered_once_per_day():
    """IDEM-1: the digest is delivered once per (campaign, UTC day) by the LOOP; the
    scheduler no longer ALSO delivers it (that double-sent the digest email/ping)."""
    storage = InMemoryStorage()
    _campaign(storage)
    digest = _CountingDigest()
    loop = _DeliveringLoop(digest)
    sched = Scheduler(storage=storage, agent_loop=loop, digest_service=digest)

    day = datetime(2026, 6, 16, 9, 0, tzinfo=UTC)
    sched.tick(day)
    sched.tick(day + timedelta(hours=1))  # same UTC day -> no second delivery
    assert digest.deliveries == 1

    sched.tick(day + timedelta(days=1))  # next day -> delivered again
    assert digest.deliveries == 2


@pytest.mark.unit
def test_scheduler_advances_ladder_email_after_timeout():
    """FR-NOTIF-2: the scheduler drives advance() so email escalates after timeout."""
    storage = InMemoryStorage()
    _campaign(storage)
    clock = _Clock()
    notifier = AppriseNotifier(
        discord_webhook_url="https://discord.test/wh",
        apprise_urls="mailto://user:pw@smtp.test",
        clock=clock,
    )
    notif_service = NotificationService(notifier)
    sched = Scheduler(
        storage=storage,
        agent_loop=_RecordingLoop(),
        notification_service=notif_service,
    )
    # Queue a web-pre-emptable approval: in-app now, Discord held 30s, email at 15m.
    notif_service.notify_decision(
        "final_approval:app-1", title="Approve?", body="Acme role"
    )
    assert notifier.sent_channels("decision:final_approval:app-1") == ["in_app"]

    # A scheduler tick at +30s fires the held Discord push (FR-NOTIF-2).
    clock.tick(30)
    out = sched.tick(clock.now)
    assert "discord" in out["ladder_fired"]
    assert "email" not in notifier.sent_channels("decision:final_approval:app-1")

    # A scheduler tick past the 15-minute timeout escalates to EMAIL — the live
    # Discord-hold -> email escalation that nothing called before.
    clock.tick(15 * 60)
    out2 = sched.tick(clock.now)
    assert "email" in out2["ladder_fired"]
    assert "email" in notifier.sent_channels("decision:final_approval:app-1")


@pytest.mark.unit
def test_acting_expires_other_channels_idempotently():
    """FR-NOTIF-3: acting on one channel no-ops the rest even as the ladder advances."""
    storage = InMemoryStorage()
    _campaign(storage)
    clock = _Clock()
    notifier = AppriseNotifier(
        discord_webhook_url="https://discord.test/wh",
        apprise_urls="mailto://user:pw@smtp.test",
        clock=clock,
    )
    notif_service = NotificationService(notifier)
    sched = Scheduler(
        storage=storage, agent_loop=_RecordingLoop(), notification_service=notif_service
    )
    notif_service.notify_decision("final_approval:app-2", title="Approve?", body="x")
    # User acts immediately on the web portal.
    notif_service.acted("final_approval:app-2")
    # Advancing far past every timeout fires NOTHING more (expired).
    clock.tick(60 * 60)
    out = sched.tick(clock.now)
    assert "email" not in out["ladder_fired"]
