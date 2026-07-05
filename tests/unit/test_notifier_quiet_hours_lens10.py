"""Regression tests for design-audit lens 10 (notifications), findings #16 and #57.

#16 — Per-channel "hold overnight" must NOT suppress the channel 24/7. The buggy
form of ``_channel_quiet_deferred`` was ``bool(pref) and self._quiet_hours is not
None`` — independent of the current time — so ``pref=True`` (e.g. "Hold Discord
overnight") deferred that channel at ALL hours, including midday, until "Deliver
now". The correct semantics: ``pref=True`` (or unset) must fall through to the
actual time-window check (``_in_quiet_hours``); only ``pref=False`` special-cases
the channel as always-through. CRITICAL/IMMEDIATE urgency must still bypass quiet
hours regardless of any per-channel preference.

#57 — A zero-length quiet window (``start == end``) must cleanly mean "quiet hours
disabled", not accidentally hold a channel 24/7 (which would happen if a per-channel
``pref=True`` short-circuited on "a window is configured" rather than "the window is
currently active").

Deterministic: an injected clock steps time so the escalation ladder fires without
real sleeps (mirrors the fixture pattern in test_notification_ladder.py).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from applicant.adapters.notification.apprise_notifier import AppriseNotifier
from applicant.ports.driven.notification import Notification, NotificationUrgency


class _Clock:
    def __init__(self, start: datetime) -> None:
        self.now = start

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


# === #16: _channel_quiet_deferred unit-level checks ==========================


def test_pref_true_does_not_defer_outside_the_quiet_window():
    """"Hold Discord overnight" (pref=True) must NOT hold Discord at midday."""
    clock = _Clock(datetime(2026, 1, 1, 12, 0, tzinfo=UTC))  # noon: outside 22-07
    n = _notifier(clock, quiet_hours=(22, 7), quiet_hours_channels={"discord": True})
    notif = Notification(title="Approve?", body="role", dedup_key="d1")
    assert n._channel_quiet_deferred("discord", notif, clock.now) is False


def test_pref_true_defers_inside_the_quiet_window():
    """The same pref=True channel IS held while the clock is inside the window."""
    clock = _Clock(datetime(2026, 1, 1, 23, 0, tzinfo=UTC))  # 23:00: inside 22-07
    n = _notifier(clock, quiet_hours=(22, 7), quiet_hours_channels={"discord": True})
    notif = Notification(title="Approve?", body="role", dedup_key="d2")
    assert n._channel_quiet_deferred("discord", notif, clock.now) is True


def test_pref_false_is_never_deferred_even_inside_the_window():
    """pref=False ("let email through") is exempt at all hours, unchanged."""
    clock = _Clock(datetime(2026, 1, 1, 23, 0, tzinfo=UTC))  # inside quiet window
    n = _notifier(clock, quiet_hours=(22, 7), quiet_hours_channels={"email": False})
    notif = Notification(title="Approve?", body="role", dedup_key="d3")
    assert n._channel_quiet_deferred("email", notif, clock.now) is False


def test_unset_channel_pref_falls_to_the_time_window_like_default():
    """A channel absent from the preference map behaves like the default (no
    special-casing): held inside the window, delivered outside it."""
    n_outside = _notifier(
        _Clock(datetime(2026, 1, 1, 12, 0, tzinfo=UTC)), quiet_hours=(22, 7)
    )
    notif = Notification(title="Approve?", body="role", dedup_key="d4")
    assert n_outside._channel_quiet_deferred("discord", notif, n_outside._clock()) is False

    n_inside = _notifier(
        _Clock(datetime(2026, 1, 1, 23, 0, tzinfo=UTC)), quiet_hours=(22, 7)
    )
    assert n_inside._channel_quiet_deferred("discord", notif, n_inside._clock()) is True


def test_critical_urgency_bypasses_quiet_hours_even_with_pref_true():
    """CRITICAL (e.g. live-takeover/CAPTCHA) must never be held, regardless of a
    per-channel "respect quiet hours" preference."""
    clock = _Clock(datetime(2026, 1, 1, 23, 0, tzinfo=UTC))  # inside quiet window
    n = _notifier(clock, quiet_hours=(22, 7), quiet_hours_channels={"discord": True})
    notif = Notification(
        title="Action needed",
        body="CAPTCHA",
        dedup_key="d5",
        urgency=NotificationUrgency.CRITICAL,
    )
    assert n._channel_quiet_deferred("discord", notif, clock.now) is False


# === #16: end-to-end through notify()/advance() ==============================


def test_end_to_end_pref_true_channel_delivers_at_midday():
    """Full ladder: enabling quiet hours with "Hold Discord overnight" (pref=True)
    must still deliver Discord at midday, not suppress it 24/7."""
    clock = _Clock(datetime(2026, 1, 1, 12, 0, tzinfo=UTC))  # noon
    n = _notifier(clock, quiet_hours=(22, 7), quiet_hours_channels={"discord": True})
    n.notify(
        Notification(
            title="Approve?", body="Acme role", dedup_key="e1", web_preemptable=True
        )
    )
    clock.tick(30)  # past the Discord hold
    n.advance()
    assert "discord" in n.sent_channels("e1")


def test_end_to_end_pref_true_channel_held_overnight_then_released():
    """The same configuration DOES hold Discord while genuinely inside the quiet
    window, and releases it once the window ends."""
    clock = _Clock(datetime(2026, 1, 1, 23, 0, tzinfo=UTC))  # inside 22-07
    n = _notifier(clock, quiet_hours=(22, 7), quiet_hours_channels={"discord": True})
    n.notify(
        Notification(
            title="Approve?", body="Acme role", dedup_key="e2", web_preemptable=True
        )
    )
    clock.tick(30)  # past the hold, but still inside the quiet window
    n.advance()
    assert "discord" not in n.sent_channels("e2")

    # Move past the window (07:00) and advance again: it should now flow through.
    clock.now = datetime(2026, 1, 2, 8, 0, tzinfo=UTC)
    n.advance()
    assert "discord" in n.sent_channels("e2")


# === #57: zero-length quiet window disables quiet hours ======================


def test_zero_length_window_disables_quiet_hours_via_in_quiet_hours():
    n = _notifier(_Clock(datetime(2026, 1, 1, 8, 0, tzinfo=UTC)), quiet_hours=("08:00", "08:00"))
    assert n._in_quiet_hours(datetime(2026, 1, 1, 8, 0, tzinfo=UTC)) is False
    assert n._in_quiet_hours(datetime(2026, 1, 1, 23, 59, tzinfo=UTC)) is False


def test_zero_length_window_does_not_hold_a_pref_true_channel():
    """A zero-length window combined with a per-channel "respect quiet hours"
    preference must not accidentally hold the channel 24/7 (the #16 failure mode
    would otherwise resurface any time a window is "configured" but empty)."""
    clock = _Clock(datetime(2026, 1, 1, 23, 0, tzinfo=UTC))
    n = _notifier(
        clock, quiet_hours=("08:00", "08:00"), quiet_hours_channels={"discord": True}
    )
    notif = Notification(title="Approve?", body="role", dedup_key="z1")
    assert n._channel_quiet_deferred("discord", notif, clock.now) is False


def test_zero_length_window_end_to_end_delivers_normally():
    clock = _Clock(datetime(2026, 1, 1, 23, 0, tzinfo=UTC))
    n = _notifier(
        clock, quiet_hours=("08:00", "08:00"), quiet_hours_channels={"discord": True}
    )
    n.notify(
        Notification(
            title="Approve?", body="Acme role", dedup_key="z2", web_preemptable=True
        )
    )
    clock.tick(30)
    n.advance()
    assert "discord" in n.sent_channels("z2")
