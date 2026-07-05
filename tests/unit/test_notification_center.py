"""Notification-center tests: in-app inbox list/seen + age-based pruning.

Covers the notifier's in-app sink as the notification center's source of truth:

- ``list_inbox`` returns enriched, newest-first entries with stable ids;
- ``mark_seen`` dismisses informational entries (and only those);
- acting on a decision (``expire``) clears its action-required inbox entry so the
  center never double-tracks acted items;
- the inbox + capture lists are pruned by AGE (24h) as well as by count.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from applicant.adapters.notification.apprise_notifier import AppriseNotifier
from applicant.application.services.notification_service import NotificationService
from applicant.ports.driven.notification import Notification, NotificationUrgency


class _Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def _notifier(now: datetime | None = None) -> tuple[AppriseNotifier, _Clock]:
    clock = _Clock(now or datetime(2026, 6, 17, 12, 0, tzinfo=UTC))
    return AppriseNotifier(in_app=True, clock=clock), clock


def test_list_inbox_enriches_and_orders_newest_first():
    notifier, _ = _notifier()
    notifier.notify(Notification(title="First", body="b1", dedup_key="d1"))
    notifier.notify(Notification(title="Second", body="b2", dedup_key="d2"))

    inbox = notifier.list_inbox()
    assert [e.title for e in inbox] == ["Second", "First"]  # newest-first
    assert all(e.id for e in inbox)  # stable ids assigned
    assert all(e.created_at is not None for e in inbox)
    assert len({e.id for e in inbox}) == 2  # ids are unique


def test_classify_kinds():
    notifier, _ = _notifier()
    # action (decision / web-preemptable)
    notifier.notify(Notification(title="Approve", body="b", dedup_key="decision:abc"))
    # error (immediate)
    notifier.notify(
        Notification(title="Oops", body="b", urgency=NotificationUrgency.IMMEDIATE, dedup_key="e1")
    )
    # digest
    notifier.notify(Notification(title="Digest", body="b", dedup_key="digest:c1"))
    # plain info
    notifier.notify(Notification(title="FYI", body="b", dedup_key="i1"))

    by_title = {e.title: e.kind for e in notifier.list_inbox()}
    assert by_title["Approve"] == "action"
    assert by_title["Oops"] == "error"
    assert by_title["Digest"] == "digest"
    assert by_title["FYI"] == "info"


def test_mark_seen_dismisses_informational_entry():
    notifier, _ = _notifier()
    notifier.notify(Notification(title="FYI", body="b", dedup_key="i1"))
    [entry] = notifier.list_inbox()

    assert notifier.mark_seen(entry.id) is True
    assert notifier.list_inbox() == []  # dropped from the default view
    # Still retrievable with include_seen, flagged seen.
    seen = notifier.list_inbox(include_seen=True)
    assert len(seen) == 1 and seen[0].seen is True
    # Unknown id is a no-op.
    assert notifier.mark_seen("nope") is False


def test_expire_clears_action_required_inbox_entry():
    notifier, _ = _notifier()
    notifier.notify(Notification(title="Approve", body="b", dedup_key="decision:abc"))
    assert len(notifier.list_inbox()) == 1
    # Acting on the decision elsewhere expires it AND drops the inbox entry.
    notifier.expire("decision:abc")
    assert notifier.list_inbox() == []


def test_unseen_entries_survive_the_age_window():
    # lens 10 #27: an unseen (never-dismissed) entry must NOT silently vanish
    # from the in-app center — it is exempt from the age prune, so a user who
    # checks back a day or two later still sees it. (Only dismissed entries and
    # the count cap age out now, and the window itself is days, not 24h.)
    notifier, clock = _notifier()
    notifier.notify(Notification(title="Old", body="b", dedup_key="old"))
    # Jump a day, then dispatch a fresh one — the old, unseen entry survives.
    clock.now = clock.now + timedelta(hours=25)
    notifier.notify(Notification(title="New", body="b", dedup_key="new"))

    titles = {e.title for e in notifier.list_inbox()}
    assert titles == {"Old", "New"}  # the unseen day-old entry survives


def test_unseen_entry_survives_on_read_without_new_dispatch():
    # lens 10 #27: even with no new dispatch to trigger a prune pass, reading the
    # inbox does not drop an unseen aged entry.
    notifier, clock = _notifier()
    notifier.notify(Notification(title="Old", body="b", dedup_key="old"))
    clock.now = clock.now + timedelta(hours=25)
    assert [e.title for e in notifier.list_inbox()] == ["Old"]


def test_count_cap_still_applies():
    notifier, _ = _notifier()
    notifier._max_inbox = 5
    notifier._max_captured = 5
    for i in range(50):
        notifier.notify(Notification(title=f"t{i}", body="b", dedup_key=f"k{i}"))
    assert len(notifier.inbox()) <= 5
    assert len(notifier.captured()) <= 5


# --- service-level delegation -------------------------------------------------
def test_service_list_and_dismiss_delegate():
    notifier, _ = _notifier()
    svc = NotificationService(notifier)
    svc.notify_digest_ready("c1", count=2)

    inbox = svc.list_inbox()
    assert len(inbox) == 1 and inbox[0].kind == "digest"
    assert svc.dismiss_notification(inbox[0].id) is True
    assert svc.list_inbox() == []


def test_service_degrades_when_notifier_has_no_inbox():
    class _Bare:
        def notify(self, _n):  # pragma: no cover - not exercised here
            return "h"

    svc = NotificationService(_Bare())
    assert svc.list_inbox() == []
    assert svc.dismiss_notification("x") is False
