"""Lens-04 finding #45: a channel dispatch that raises must not be recorded as delivered.

``_fire_due`` used to catch the dispatch exception, log it, and then unconditionally set
``rung.fired = True`` and append the channel to ``sent_channels`` regardless of outcome. A
broken Discord webhook or dead SMTP relay therefore looked "delivered" everywhere the ladder
state is read (``sent_channels`` / ``ladder_status``), the IMMEDIATE "agent stuck" alert was
silently lost, and there was no retry.

The fix leaves a failed rung UN-fired: each rung's ``due_at`` is independent of its
siblings (the loop does not gate a later hop on an earlier one having fired), so leaving it
unfired means the next ``advance()`` tick re-scans and retries it, without wedging the rest
of the ladder.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from applicant.adapters.notification.apprise_notifier import AppriseNotifier
from applicant.ports.driven.notification import Notification, NotificationUrgency


class _Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def tick(self, seconds: float) -> None:
        self.now = self.now + timedelta(seconds=seconds)


def _notifier(clock) -> AppriseNotifier:
    return AppriseNotifier(
        discord_webhook_url="https://discord.test/wh",
        apprise_urls="mailto://user:pw@smtp.test",
        clock=clock,
    )


def test_failed_channel_is_not_recorded_as_sent():
    """A raising dispatch must not land the channel in ``sent_channels``."""
    clock = _Clock()
    n = _notifier(clock)
    real_dispatch = n._dispatch

    def raising_dispatch(channel, notification):
        if channel == "discord":
            raise RuntimeError("Discord webhook unreachable")
        real_dispatch(channel, notification)

    n._dispatch = raising_dispatch  # type: ignore[method-assign]

    # IMMEDIATE fans out to every configured channel at once (in_app + discord + email).
    n.notify(
        Notification(
            title="Agent stuck",
            body="needs attention",
            dedup_key="stuck",
            urgency=NotificationUrgency.IMMEDIATE,
        )
    )

    sent = n.sent_channels("stuck")
    assert "discord" not in sent, "a failed dispatch must not be recorded as delivered"

    # Its rung must not be marked fired/delivered either (was falsely marked before).
    status = n.ladder_status("stuck")
    assert status is not None
    discord_rung = next(c for c in status["channels"] if c["channel"] == "discord")
    assert discord_rung["fired"] is False, (
        "a failed channel's rung must stay un-fired, not be marked delivered"
    )


def test_successful_channel_is_still_recorded_as_sent():
    """Successful-delivery behavior is unchanged: a healthy channel still records."""
    clock = _Clock()
    n = _notifier(clock)
    real_dispatch = n._dispatch

    def raising_dispatch(channel, notification):
        if channel == "discord":
            raise RuntimeError("Discord webhook unreachable")
        real_dispatch(channel, notification)

    n._dispatch = raising_dispatch  # type: ignore[method-assign]

    n.notify(
        Notification(
            title="Agent stuck",
            body="needs attention",
            dedup_key="stuck2",
            urgency=NotificationUrgency.IMMEDIATE,
        )
    )

    sent = n.sent_channels("stuck2")
    assert "email" in sent
    assert "in_app" in sent


def test_ladder_still_progresses_when_one_rung_fails():
    """A failing rung must not wedge sibling rungs due on the same tick."""
    clock = _Clock()
    n = _notifier(clock)
    real_dispatch = n._dispatch

    def raising_dispatch(channel, notification):
        if channel == "discord":
            raise RuntimeError("Discord webhook unreachable")
        real_dispatch(channel, notification)

    n._dispatch = raising_dispatch  # type: ignore[method-assign]

    # CRITICAL fans every channel out at once, so email/in_app are due on the SAME tick
    # as the failing Discord rung -- proving one bad channel does not block the others.
    n.notify(
        Notification(
            title="Live takeover needed",
            body="captcha",
            dedup_key="crit",
            urgency=NotificationUrgency.CRITICAL,
        )
    )

    sent = set(n.sent_channels("crit"))
    assert "discord" not in sent
    assert "email" in sent
    assert "in_app" in sent


def test_failed_rung_retries_on_a_later_tick():
    """Leaving the rung un-fired means the next advance() tick retries the same channel."""
    clock = _Clock()
    n = _notifier(clock)
    real_dispatch = n._dispatch
    attempts: list[str] = []

    def flaky_dispatch(channel, notification):
        if channel == "discord":
            attempts.append(channel)
            if len(attempts) == 1:
                raise RuntimeError("Discord webhook unreachable (first attempt)")
        real_dispatch(channel, notification)

    n._dispatch = flaky_dispatch  # type: ignore[method-assign]

    n.notify(
        Notification(
            title="Agent stuck",
            body="needs attention",
            dedup_key="retry",
            urgency=NotificationUrgency.IMMEDIATE,
        )
    )
    assert "discord" not in n.sent_channels("retry")

    # A later scheduler tick re-scans the still-due, still-unfired rung and retries it.
    clock.tick(1)
    fired = n.advance()
    assert "discord" in fired
    assert "discord" in n.sent_channels("retry")
    assert len(attempts) == 2, "the failed channel should have been retried exactly once"
