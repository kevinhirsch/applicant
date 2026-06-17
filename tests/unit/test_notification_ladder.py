"""Notification escalation ladder + idempotency + quiet hours (FR-NOTIF-2/3/5).

Deterministic: an injected clock steps time so the 30s Discord hold and 15-min email
escalation fire without real sleeps.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from applicant.adapters.notification.apprise_notifier import AppriseNotifier
from applicant.application.services.notification_service import NotificationService
from applicant.ports.driven.notification import Notification, NotificationUrgency


class _Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def tick(self, seconds: float) -> None:
        self.now = self.now + timedelta(seconds=seconds)


def _notifier(clock, **kw):
    return AppriseNotifier(
        discord_webhook_url="https://discord.test/wh",
        apprise_urls="mailto://user:pw@smtp.test",
        clock=clock,
        **kw,
    )


def test_discord_held_then_email_escalation():
    # FR-NOTIF-2: web-pre-emptable approval holds Discord 30s; email after 15 min.
    clock = _Clock()
    n = _notifier(clock)
    n.notify(
        Notification(title="Approve?", body="Acme role", dedup_key="k1", web_preemptable=True)
    )
    # in-app fires immediately; Discord held; email pending.
    assert n.sent_channels("k1") == ["in_app"]
    clock.tick(30)
    n.advance()
    assert "discord" in n.sent_channels("k1")
    assert "email" not in n.sent_channels("k1")
    clock.tick(15 * 60)
    n.advance()
    assert "email" in n.sent_channels("k1")


def test_presence_preempts_discord():
    # FR-NOTIF-2: verifiable web presence surfaces in-app instead of Discord.
    clock = _Clock()
    n = _notifier(clock, presence=lambda: True)
    n.notify(
        Notification(title="Approve?", body="role", dedup_key="k2", web_preemptable=True)
    )
    clock.tick(30)
    n.advance()
    assert "discord" not in n.sent_channels("k2")
    assert "in_app" in n.sent_channels("k2")


def test_acting_on_one_channel_expires_others():
    # FR-NOTIF-3: acting on one channel no-ops the others.
    clock = _Clock()
    n = _notifier(clock)
    svc = NotificationService(n)
    svc.notify_decision("app-1", title="Approve?", body="role")
    key = svc.dedup_key("app-1")
    assert n.is_active(key)
    svc.acted("app-1")
    assert not n.is_active(key)
    # Advancing past the hold never fires Discord/email now.
    clock.tick(20 * 60)
    fired = n.advance()
    assert fired == []


def test_immediate_errors_fan_out_any_hour():
    # FR-NOTIF-5: errors surface immediately across every channel.
    clock = _Clock()
    n = _notifier(clock, quiet_hours=(0, 23))  # nearly always quiet
    n.notify(
        Notification(
            title="Run failed", body="boom", urgency=NotificationUrgency.IMMEDIATE, dedup_key="e1"
        )
    )
    channels = set(n.sent_channels("e1"))
    assert {"discord", "in_app", "email"} <= channels


def test_quiet_hours_defer_normal_but_not_in_app():
    # FR-NOTIF-5: NORMAL approvals defer external channels during quiet hours.
    clock = _Clock()
    clock.now = datetime(2026, 1, 1, 23, 30, tzinfo=UTC)  # inside 22-07 quiet window
    n = _notifier(clock, quiet_hours=(22, 7))
    n.notify(Notification(title="Approve?", body="role", dedup_key="q1"))
    # in-app surfaces; Discord deferred while quiet.
    assert "in_app" in n.sent_channels("q1")
    assert "discord" not in n.sent_channels("q1")
    # Move to 08:00 (out of quiet hours) and advance.
    clock.now = datetime(2026, 1, 2, 8, 0, tzinfo=UTC)
    n.advance()
    assert "discord" in n.sent_channels("q1")


def test_always_on_ignores_quiet_hours():
    clock = _Clock()
    clock.now = datetime(2026, 1, 1, 23, 30, tzinfo=UTC)
    n = _notifier(clock, quiet_hours=(22, 7), always_on=True)
    n.notify(Notification(title="Approve?", body="role", dedup_key="a1"))
    assert "discord" in n.sent_channels("a1")


@pytest.mark.contract
def test_in_app_inbox_feeds_portal():
    # In-app notifications are captured for the pending-actions feed (FR-UI-3).
    clock = _Clock()
    n = AppriseNotifier(in_app=True, clock=clock)
    n.notify(Notification(title="hi", body="there", dedup_key="i1"))
    assert any(c.title == "hi" for c in n.inbox())


# === #15: digest-ready ping per-(campaign, UTC-day) idempotency ============
def test_digest_ready_ping_once_per_day_across_fresh_loops():
    """#15: 3 same-day calls (as a fresh AgentLoop per tick would make) -> exactly 1
    digest-ready ping; a NEW UTC day pings again."""
    calls: list[str] = []

    class _CountingNotifier:
        def notify(self, n):
            calls.append(n.dedup_key)
            return f"handle-{len(calls)}"

        def expire(self, k):  # pragma: no cover - not exercised
            pass

    svc = NotificationService(_CountingNotifier())
    cid = "camp-1"
    day = datetime(2026, 6, 16, 9, 0, tzinfo=UTC)

    # Three same-day ticks (the shared service survives the loop being rebuilt).
    svc.notify_digest_ready(cid, count=3, now=day)
    svc.notify_digest_ready(cid, count=3, now=day.replace(hour=10))
    svc.notify_digest_ready(cid, count=3, now=day.replace(hour=11))
    assert len(calls) == 1  # exactly one ready ping that day

    # A new UTC day fires again.
    svc.notify_digest_ready(cid, count=2, now=day + timedelta(days=1))
    assert len(calls) == 2
