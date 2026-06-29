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


def test_fresh_presence_heartbeat_suppresses_discord():
    # FR-NOTIF-2: a recent set_presence(True) heartbeat suppresses the Discord push.
    clock = _Clock()
    n = _notifier(clock)
    n.notify(
        Notification(title="Approve?", body="role", dedup_key="kp1", web_preemptable=True)
    )
    n.set_presence(True)  # the client heartbeat just before the Discord hop is due
    clock.tick(30)
    n.advance()
    assert "discord" not in n.sent_channels("kp1")
    assert "in_app" in n.sent_channels("kp1")


def test_stale_presence_decays_so_discord_resumes():
    # FR-NOTIF-2: a one-shot presence signal must NOT suppress Discord forever — once
    # the heartbeats stop (user walked away) the freshness window lapses and the
    # Discord escalation resumes for a notification that arrives later.
    clock = _Clock()
    n = _notifier(clock)
    n.set_presence(True)  # user glanced at the UI once...
    clock.tick(5 * 60)    # ...then left for five minutes (no further heartbeat)
    n.notify(
        Notification(title="Approve?", body="role", dedup_key="kp2", web_preemptable=True)
    )
    clock.tick(30)
    n.advance()
    assert "discord" in n.sent_channels("kp2")


def test_presence_false_clears_the_window_immediately():
    # FR-NOTIF-2: present:false (tab blurred / hidden) resumes Discord at once.
    clock = _Clock()
    n = _notifier(clock)
    n.set_presence(True)
    n.set_presence(False)
    n.notify(
        Notification(title="Approve?", body="role", dedup_key="kp3", web_preemptable=True)
    )
    clock.tick(30)
    n.advance()
    assert "discord" in n.sent_channels("kp3")


def test_email_timeout_is_reconfigurable_at_runtime():
    # FR-NOTIF-2: the email-escalation delay is UI-configurable; reconfiguring the
    # live notifier shortens (or lengthens) the email hop without a restart.
    clock = _Clock()
    n = _notifier(clock)
    n.configure(email_timeout_seconds=5 * 60)  # was 15 min; now 5
    n.notify(
        Notification(title="Approve?", body="role", dedup_key="kt", web_preemptable=True)
    )
    clock.tick(30)
    n.advance()  # Discord hop
    clock.tick(5 * 60)
    n.advance()
    assert "email" in n.sent_channels("kt")


def test_email_timeout_reconfigure_clamps_to_a_floor():
    clock = _Clock()
    n = _notifier(clock)
    n.configure(email_timeout_seconds=0)  # must not become an instant email
    n.notify(
        Notification(title="Approve?", body="role", dedup_key="ktc", web_preemptable=True)
    )
    clock.tick(30)
    n.advance()
    assert "email" not in n.sent_channels("ktc")


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


# === FR-NOTIF-5: quiet-window math (HH:MM precision, wrap-around, timezone) ====
def test_quiet_window_hhmm_inside_and_outside():
    # An "HH:MM" window is evaluated to the minute, not just the hour.
    n = _notifier(_Clock(), quiet_hours=("22:30", "07:15"))
    inside_late = datetime(2026, 1, 1, 22, 45, tzinfo=UTC)
    inside_early = datetime(2026, 1, 2, 7, 0, tzinfo=UTC)
    boundary_just_before = datetime(2026, 1, 1, 22, 29, tzinfo=UTC)
    at_end = datetime(2026, 1, 2, 7, 15, tzinfo=UTC)  # end is exclusive
    assert n._in_quiet_hours(inside_late) is True
    assert n._in_quiet_hours(inside_early) is True
    assert n._in_quiet_hours(boundary_just_before) is False
    assert n._in_quiet_hours(at_end) is False


def test_quiet_window_same_day_no_wrap():
    # A daytime window that does NOT cross midnight (09:00-17:00).
    n = _notifier(_Clock(), quiet_hours=("09:00", "17:00"))
    assert n._in_quiet_hours(datetime(2026, 1, 1, 12, 0, tzinfo=UTC)) is True
    assert n._in_quiet_hours(datetime(2026, 1, 1, 8, 59, tzinfo=UTC)) is False
    assert n._in_quiet_hours(datetime(2026, 1, 1, 17, 0, tzinfo=UTC)) is False


def test_quiet_window_equal_start_end_is_disabled():
    n = _notifier(_Clock(), quiet_hours=("08:00", "08:00"))
    assert n._in_quiet_hours(datetime(2026, 1, 1, 8, 0, tzinfo=UTC)) is False


def test_quiet_window_respects_timezone():
    # 22:00-07:00 in America/Phoenix (UTC-7, no DST). 06:00 UTC == 23:00 MST = quiet;
    # 16:00 UTC == 09:00 MST = not quiet. Without the tz it would read UTC hours.
    n = _notifier(_Clock(), quiet_hours=("22:00", "07:00"), quiet_tz="America/Phoenix")
    assert n._in_quiet_hours(datetime(2026, 1, 1, 6, 0, tzinfo=UTC)) is True
    assert n._in_quiet_hours(datetime(2026, 1, 1, 16, 0, tzinfo=UTC)) is False


def test_quiet_window_bad_timezone_degrades_to_utc():
    # An unknown tz name must not crash the dispatch path — it falls back to UTC.
    n = _notifier(_Clock(), quiet_hours=("22:00", "07:00"), quiet_tz="Not/AZone")
    assert n._in_quiet_hours(datetime(2026, 1, 1, 23, 0, tzinfo=UTC)) is True


def test_errors_immediate_during_hhmm_quiet_window():
    # FR-NOTIF-5: errors fan out to every channel even mid-quiet-window.
    clock = _Clock()
    clock.now = datetime(2026, 1, 1, 23, 30, tzinfo=UTC)  # inside 22:30-07:15
    n = _notifier(clock, quiet_hours=("22:30", "07:15"))
    n.notify(
        Notification(
            title="Run failed",
            body="boom",
            urgency=NotificationUrgency.IMMEDIATE,
            dedup_key="e-qh",
        )
    )
    assert {"discord", "in_app", "email"} <= set(n.sent_channels("e-qh"))


def test_info_held_then_delivered_after_hhmm_quiet_window():
    # FR-NOTIF-5: a NORMAL approval created mid-window holds the push channels and
    # delivers them once the window ends (the existing escalation-hold mechanism).
    clock = _Clock()
    clock.now = datetime(2026, 1, 1, 23, 30, tzinfo=UTC)  # inside 22:30-07:15
    n = _notifier(clock, quiet_hours=("22:30", "07:15"))
    n.notify(Notification(title="Approve?", body="role", dedup_key="q-hhmm"))
    # In-app always surfaces; Discord/email held while quiet.
    assert "in_app" in n.sent_channels("q-hhmm")
    assert "discord" not in n.sent_channels("q-hhmm")
    # Step to 07:16 (just past the window end) and advance.
    clock.now = datetime(2026, 1, 2, 7, 16, tzinfo=UTC)
    n.advance()
    assert "discord" in n.sent_channels("q-hhmm")


def test_configure_sets_quiet_hours_live():
    # The live adapter can flip quiet hours on/off without a restart (zero-CLI).
    clock = _Clock()
    clock.now = datetime(2026, 1, 1, 23, 30, tzinfo=UTC)
    n = _notifier(clock)  # no quiet hours initially
    assert n._in_quiet_hours(clock.now) is False
    n.configure(quiet_hours=("22:00", "07:00"), quiet_tz="", always_on=False)
    assert n._in_quiet_hours(clock.now) is True
    # 24/7 mode (always_on) turns it back off.
    n.configure(always_on=True)
    assert n._in_quiet_hours(clock.now) is False


@pytest.mark.contract
def test_in_app_inbox_feeds_portal():
    # In-app notifications are captured for the pending-actions feed (FR-UI-3).
    clock = _Clock()
    n = AppriseNotifier(in_app=True, clock=clock)
    n.notify(Notification(title="hi", body="there", dedup_key="i1"))
    assert any(c.title == "hi" for c in n.inbox())


# === G15 regression suite ====================================================

# --- #233: dedup key written AFTER dispatch, not before ----------------------
def test_233_failed_send_does_not_consume_dedup_key():
    """A failing first dispatch must not permanently suppress a retry."""
    clock = _Clock()
    n = AppriseNotifier(apprise_urls="mailto://u:p@smtp.test", clock=clock)
    calls: list[int] = []
    real_dispatch = n._dispatch

    def flaky(channel, notification):
        calls.append(len(calls) + 1)
        if len(calls) == 1:
            raise RuntimeError("SMTP error")
        real_dispatch(channel, notification)

    n._dispatch = flaky  # type: ignore[method-assign]
    key = "digest_email:c1:2026-01-01"
    try:
        n.send_email(subject="S", html="H", dedup_key=key)
    except RuntimeError:
        pass
    # retry must succeed (key not yet registered because first dispatch failed)
    result = n.send_email(subject="S", html="H", dedup_key=key)
    assert result is True
    assert len([c for c in n.captured() if c.channel == "email"]) == 1


def test_233_happy_path_idempotency_preserved():
    """Successful first send still blocks a duplicate."""
    clock = _Clock()
    n = AppriseNotifier(apprise_urls="mailto://u:p@smtp.test", clock=clock)
    key = "digest_email:c1:2026-01-01"
    n.send_email(subject="S", html="H", dedup_key=key)
    n.send_email(subject="S", html="H", dedup_key=key)
    assert len([c for c in n.captured() if c.channel == "email"]) == 1


# --- #234: per-channel failure isolation -------------------------------------
def test_234_one_channel_failure_does_not_abort_others():
    """A raising dispatch on one notification must not drop another's rung."""
    clock = _Clock()
    n = AppriseNotifier(discord_webhook_url="https://discord.test/wh", clock=clock)
    real_dispatch = n._dispatch

    def selective(channel, notification):
        if notification.dedup_key == "bad":
            raise RuntimeError("unreachable")
        real_dispatch(channel, notification)

    n._dispatch = selective  # type: ignore[method-assign]

    n.notify(Notification(title="bad", body="x", dedup_key="bad"))
    n.notify(Notification(title="good", body="y", dedup_key="good"))
    clock.tick(30)
    n.advance()  # must not raise
    assert "discord" in n.sent_channels("good")


# --- #235: _sent dict lock ---------------------------------------------------
def test_235_sent_lock_exists():
    """The notifier exposes _sent_lock (a threading.Lock) for safe concurrent access."""
    import threading
    n = AppriseNotifier(discord_webhook_url="https://discord.test/wh")
    assert hasattr(n, "_sent_lock")
    assert isinstance(n._sent_lock, type(threading.Lock()))


# --- #236: constructor floors email_timeout ----------------------------------
def test_236_constructor_floors_zero_timeout():
    """email_timeout_seconds=0 in the constructor is clamped to the 60s floor."""
    clock = _Clock()
    n = AppriseNotifier(
        apprise_urls="mailto://u:p@smtp.test",
        clock=clock,
        email_timeout_seconds=0,
    )
    n.notify(Notification(title="A", body="b", dedup_key="f1", web_preemptable=True))
    # in-app should have fired; email must NOT fire on the same tick
    fired = [c.channel for c in n.captured()]
    assert "in_app" in fired
    assert "email" not in fired


def test_236_constructor_preserves_valid_timeout():
    """A valid (above-floor) timeout is not altered by the constructor."""
    n = AppriseNotifier(
        apprise_urls="mailto://u:p@smtp.test",
        email_timeout_seconds=600,
    )
    assert n._email_timeout == 600


# --- #172/#302: quiet hours (green regression) --------------------------------
def test_172_quiet_hours_defer_normal_external_channels():
    """NORMAL notifications defer Discord/email during quiet hours (#172 green)."""
    clock = _Clock()
    clock.now = datetime(2026, 1, 1, 3, 0, tzinfo=UTC)  # 03:00, inside 22:00–07:00
    n = _notifier(clock, quiet_hours=(22, 7))
    n.notify(Notification(title="A", body="b", dedup_key="qn"))
    clock.tick(30 * 60)
    n.advance()
    assert "discord" not in n.sent_channels("qn")
    assert "in_app" in n.sent_channels("qn")


def test_302_hhmm_window_precision():
    """HH:MM quiet window is evaluated to the minute, not just the hour (#302)."""
    n = _notifier(_Clock(), quiet_hours=("22:30", "07:15"))
    assert n._in_quiet_hours(datetime(2026, 1, 1, 22, 45, tzinfo=UTC)) is True
    assert n._in_quiet_hours(datetime(2026, 1, 1, 22, 15, tzinfo=UTC)) is False
    assert n._in_quiet_hours(datetime(2026, 1, 2, 7, 14, tzinfo=UTC)) is True
    assert n._in_quiet_hours(datetime(2026, 1, 2, 7, 15, tzinfo=UTC)) is False


# --- #300: ntfy push channel -------------------------------------------------
def test_300_ntfy_channel_in_enum():
    """NotificationChannel exposes both NTFY and PUSH members (#300)."""
    from applicant.ports.driven.notification import NotificationChannel
    assert hasattr(NotificationChannel, "NTFY")
    assert hasattr(NotificationChannel, "PUSH")
    assert NotificationChannel.NTFY.value == "ntfy"


def test_300_notifier_accepts_ntfy_url():
    """AppriseNotifier accepts ntfy_url and includes ntfy in configured_channels."""
    n = AppriseNotifier(
        discord_webhook_url="https://discord.test/wh",
        ntfy_url="https://ntfy.test/topic",
    )
    assert n.has_ntfy() is True
    assert "ntfy" in n.configured_channels()


def test_300_immediate_notification_dispatched_to_ntfy():
    """An IMMEDIATE notification fans out to the ntfy channel."""
    clock = _Clock()
    n = AppriseNotifier(
        discord_webhook_url="https://discord.test/wh",
        ntfy_url="https://ntfy.test/topic",
        clock=clock,
    )
    n.notify(
        Notification(
            title="Takeover needed",
            body="CAPTCHA",
            urgency=NotificationUrgency.IMMEDIATE,
            deep_link="/takeover/session-1",
            dedup_key="to1",
        )
    )
    ntfy_sends = [c for c in n.captured() if c.channel == "ntfy"]
    assert ntfy_sends
    assert ntfy_sends[0].deep_link == "/takeover/session-1"


def test_300_ntfy_configure_update():
    """configure(ntfy_url=...) updates the ntfy channel on the live adapter."""
    n = AppriseNotifier(discord_webhook_url="https://discord.test/wh")
    assert not n.has_ntfy()
    n.configure(ntfy_url="https://ntfy.test/topic")
    assert n.has_ntfy() is True


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
