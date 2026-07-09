"""Regression test for DISC-14 (docs/design/audits/discovered-issues.md).

``notify()``, ``advance()``, and ``deliver_now()`` used to each take/compute their
own timestamp, and ``_build_rungs`` took its OWN later clock read for ``due_at`` —
so three independent reads of a real wall clock inside one ``notify()`` call could
disagree by a few microseconds. If the read used to compute a rung's ``due_at``
happened to land LATER than the read used moments after to compare against it
(clock drift/jitter, or simply system-clock adjustment), a rung meant to fire
immediately would look like it was due microseconds in the FUTURE and silently
get skipped for that tick.

The fix threads a single ``now`` value through ``notify()`` -> ``_build_rungs()``
-> ``_fire_due()`` (one clock read per operation), so a rung built as due "now" is
always compared against that exact same instant.

This test uses a clock that returns a strictly DECREASING value on every call (the
worst-case jitter direction for the old three-read bug: each subsequent read looks
EARLIER than the one before). Against the old three-reads-per-call implementation
this reproduces the skip; against the fixed single-read implementation the rung
fires every time because the whole call only ever reads the clock once.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from applicant.adapters.notification.apprise_notifier import AppriseNotifier
from applicant.ports.driven.notification import Notification, NotificationUrgency


class _DecreasingClock:
    """Returns a value a few microseconds EARLIER than the previous call, every call.

    Models the worst-case direction of clock jitter across independent reads: if
    code reads this clock more than once while computing a "due now, fire now"
    decision, each successive read looks like it happened before the last one —
    exactly the scenario that made the old multi-read notifier code skip a rung
    that should have fired immediately.
    """

    def __init__(self, start: datetime) -> None:
        self._value = start
        self.call_count = 0

    def __call__(self) -> datetime:
        self.call_count += 1
        current = self._value
        self._value = self._value - timedelta(microseconds=5)
        return current


def test_immediate_notification_fires_every_channel_despite_clock_drift():
    """An IMMEDIATE notification's rungs are all due "now" — with a drifting clock,
    the old multi-read implementation could see a later _build_rungs() read produce
    a due_at that looked ahead of the earlier-drifting _fire_due() comparison read,
    silently skipping the rung. The fix (one read threaded through the whole call)
    means this can never happen: due_at and the comparison instant are identical."""
    clock = _DecreasingClock(datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC))
    n = AppriseNotifier(
        discord_webhook_url="https://discord.test/wh",
        apprise_urls="mailto://user:pw@smtp.test",
        ntfy_url="https://ntfy.test/topic",
        clock=clock,
    )

    n.notify(
        Notification(
            title="Your job-search agent is stuck",
            body="boom",
            urgency=NotificationUrgency.IMMEDIATE,
            dedup_key="disc14-immediate",
        )
    )

    # Every configured channel fired in this same call — nothing was left pending
    # because a fresher/staler clock read made its due_at look like the future.
    fired = set(n.sent_channels("disc14-immediate"))
    assert fired == {"discord", "email", "ntfy", "in_app"}
    assert n.pending_escalations("disc14-immediate") == []


def test_normal_in_app_rung_due_now_fires_despite_clock_drift():
    """The NORMAL in-app rung is also built with due_at == now and must fire in the
    same notify() call, not get held over to the next advance() tick."""
    clock = _DecreasingClock(datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC))
    n = AppriseNotifier(clock=clock, in_app=True)

    n.notify(
        Notification(
            title="Daily digest ready",
            body="3 viable roles await your review.",
            dedup_key="disc14-normal",
            urgency=NotificationUrgency.NORMAL,
        )
    )

    assert "in_app" in n.sent_channels("disc14-normal")
    assert n.pending_escalations("disc14-normal") == []


def test_notify_reads_the_clock_once_for_the_due_at_vs_ts_comparison():
    """Direct assertion of the DISC-14 fix shape: one notify() call for a
    single-rung-due-now notification should read the clock exactly once to decide
    both the rung's due_at and the instant it fires against (a couple of additional,
    UNRELATED reads happen for bookkeeping like _dispatch's captured-at timestamp,
    so this only pins the count for a config with no dispatch-time bookkeeping
    reads triggered, i.e. no channels configured beyond the local in-app sink)."""
    clock = _DecreasingClock(datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC))
    n = AppriseNotifier(clock=clock, in_app=True)

    n.notify(
        Notification(
            title="Status",
            body="ok",
            dedup_key="disc14-count",
            urgency=NotificationUrgency.NORMAL,
        )
    )

    # notify() itself takes exactly one now-for-due-at-and-ts read; _dispatch takes
    # one more read for the captured entry's created_at (a separate, legitimate
    # purpose untouched by this fix). Two reads total, not three-plus, and — the
    # real point — the SAME value threaded through due_at and the firing ts, so the
    # rung is never judged against an instant later than the value used to construct
    # its own due_at.
    assert clock.call_count == 2
    assert "in_app" in n.sent_channels("disc14-count")
