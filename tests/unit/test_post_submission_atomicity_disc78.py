"""Regression tests for the discovered-issues ledger DISC-7 / DISC-8.

DISC-7 (high) -- ``send_scheduled_follow_ups`` used to notify (send) FIRST and
only flip the row's status to ``SENT`` afterwards. If that post-send flip
raised, the row silently stayed ``SCHEDULED`` -- so ``list_due`` handed the
SAME follow-up straight back on the very next tick, violating the "sent AT
MOST ONCE" contract in the method's own docstring. The fix reorders the write
so the row is durably flipped to ``SENT`` BEFORE the send is even attempted:
a send is only ever attempted once we can already prove it happened, so the
only way to fail is to fail BEFORE sending (never resend) -- and a genuine
send failure (the notifier actually raised) explicitly reverts the flip so
the row is retried, never lost.

DISC-8 (med) -- ``check_ghosting`` added the ``GhostingSignal`` row
unconditionally, before attempting the GHOSTED status flip. If the flip
failed, the application stayed re-matchable (still AWAITING_RESPONSE /
POST_SUBMISSION) and the NEXT day's sweep recorded a SECOND signal for the
exact same application, piling up duplicates every re-sweep until the flip
happened to succeed. The fix makes signal-recording idempotent per
application: once a signal is already on file for an application, a re-sweep
retries the flip without recording a duplicate.

Hermetic: ``InMemoryStorage``, no DB. Every scenario below was hand-verified
RED against the pre-fix ``post_submission_service.py`` (restored from a
``cp``-backup) and GREEN against the fixed version.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.post_submission_service import PostSubmissionService
from applicant.core.entities.application import Application
from applicant.core.entities.follow_up import FollowUpStatus, FollowUpTemplate
from applicant.core.entities.outcome_event import OutcomeEvent
from applicant.core.entities.submission_snapshot import SubmissionSnapshot
from applicant.core.ids import (
    ApplicationId,
    CampaignId,
    JobPostingId,
    OutcomeEventId,
    SubmissionSnapshotId,
    new_id,
)
from applicant.core.state_machine import ApplicationState


def _app(cid, status=ApplicationState.AWAITING_RESPONSE):
    return Application(
        id=ApplicationId(new_id()),
        campaign_id=cid,
        posting_id=JobPostingId(new_id()),
        status=status,
        root_url="https://example.com/job/1",
    )


def _seed_submitted(storage, app, *, days_ago: float) -> None:
    storage.outcomes.add(
        OutcomeEvent(id=OutcomeEventId(new_id()), application_id=app.id, type="submitted")
    )
    storage.submission_snapshots.add(
        SubmissionSnapshot(
            id=SubmissionSnapshotId(new_id()),
            application_id=app.id,
            captured_at=datetime.now(UTC) - timedelta(days=days_ago),
        )
    )


# --- DISC-7: follow-up "sent at most once" ----------------------------------


class _AlwaysRaisingFollowUps:
    """Wraps the real follow-up repo but makes ``update`` always raise --
    simulates the "mark as sent" persistence step being permanently broken."""

    def __init__(self, real):
        self._real = real

    def update(self, f):
        raise RuntimeError("boom: follow_ups.update failed")

    def __getattr__(self, name):
        return getattr(self._real, name)


class _OrderTrackingFollowUps:
    """Wraps the real follow-up repo and records the STATUS of every
    ``update`` call, so a test can assert the flip happens BEFORE the send
    rather than after (the exact ordering DISC-7 hinges on)."""

    def __init__(self, real, events):
        self._real = real
        self._events = events

    def update(self, f):
        self._events.append(f"db_update:{f.status.value}")
        self._real.update(f)

    def __getattr__(self, name):
        return getattr(self._real, name)


class _FlakyNotifier:
    """First call raises (a genuine send failure); subsequent calls succeed."""

    def __init__(self, events=None, fail_times=1):
        self.calls = 0
        self._fail_times = fail_times
        self._events = events

    def notify_decision(self, decision_ref, *, title, body, deep_link=None):
        self.calls += 1
        if self._events is not None:
            self._events.append("notify")
        if self.calls <= self._fail_times:
            raise RuntimeError("boom: notify_decision failed")
        return "handle"


@pytest.mark.unit
class TestFollowUpSentAtMostOnce:
    def test_broken_mark_sent_never_attempts_the_send_and_stays_retryable(self):
        """DISC-7: if we can't durably record SENT, we must not send at all --
        an un-recorded send is exactly the failure mode that used to cause a
        resend. Across repeated ticks with a permanently-broken flip, the
        notifier must NEVER be invoked (zero risk of ever double-sending)."""
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        app = _app(cid)
        storage.applications.add(app)
        notifier = _FlakyNotifier(fail_times=0)  # would always succeed if called
        service = PostSubmissionService(storage, notification_service=notifier)
        fup = service.schedule_follow_up(
            app.id, template=FollowUpTemplate.CHECK_IN, delay_hours=-1
        )
        storage.follow_ups = _AlwaysRaisingFollowUps(storage.follow_ups)

        now = datetime.now(UTC)
        first = service.send_scheduled_follow_ups(now=now)
        second = service.send_scheduled_follow_ups(now=now + timedelta(minutes=1))

        assert first == []
        assert second == []
        assert notifier.calls == 0, "the send must never be attempted if it can't be recorded"
        # The row is untouched by the raising wrapper, so the ORIGINAL fup is
        # still exactly SCHEDULED underneath -- safely retryable forever.
        assert fup.status == FollowUpStatus.SCHEDULED

    def test_flip_is_committed_before_the_send_is_attempted(self):
        """Structural regression: the DB write marking SENT must happen
        BEFORE the notify call, not after -- eliminating the vulnerable
        post-send window DISC-7 exploited."""
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        app = _app(cid)
        storage.applications.add(app)
        events: list[str] = []
        notifier = _FlakyNotifier(events=events, fail_times=0)
        service = PostSubmissionService(storage, notification_service=notifier)
        service.schedule_follow_up(app.id, template=FollowUpTemplate.CHECK_IN, delay_hours=-1)
        storage.follow_ups = _OrderTrackingFollowUps(storage.follow_ups, events)

        service.send_scheduled_follow_ups()

        assert events == ["db_update:SENT", "notify"], (
            "the SENT flip must be durably written before the send is attempted"
        )

    def test_genuine_send_failure_reverts_and_still_retries(self):
        """A REAL send failure (the notifier raised, nothing went out) must
        still retry next tick -- the DISC-7 fix must not turn every send
        failure into a permanently-lost follow-up."""
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        app = _app(cid)
        storage.applications.add(app)
        notifier = _FlakyNotifier(fail_times=1)  # fails once, then succeeds
        service = PostSubmissionService(storage, notification_service=notifier)
        fup = service.schedule_follow_up(
            app.id, template=FollowUpTemplate.CHECK_IN, delay_hours=-1
        )

        now = datetime.now(UTC)
        first = service.send_scheduled_follow_ups(now=now)

        assert first == []
        assert notifier.calls == 1
        # Reverted back to SCHEDULED so the next tick retries it.
        assert storage.follow_ups.get(fup.id).status == FollowUpStatus.SCHEDULED
        assert fup.id in [f.id for f in storage.follow_ups.list_due(now)]

        second = service.send_scheduled_follow_ups(now=now + timedelta(minutes=1))

        assert [f.id for f in second] == [fup.id]
        assert notifier.calls == 2
        assert storage.follow_ups.get(fup.id).status == FollowUpStatus.SENT

    def test_sent_at_most_once_across_many_retried_ticks(self):
        """End-to-end DISC-7 guarantee: however many ticks run, a follow-up
        that eventually sends is notified EXACTLY once, never twice."""
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        app = _app(cid)
        storage.applications.add(app)
        notifier = _FlakyNotifier(fail_times=2)
        service = PostSubmissionService(storage, notification_service=notifier)
        fup = service.schedule_follow_up(
            app.id, template=FollowUpTemplate.CHECK_IN, delay_hours=-1
        )

        now = datetime.now(UTC)
        for i in range(5):
            service.send_scheduled_follow_ups(now=now + timedelta(minutes=i))

        assert notifier.calls == 3  # 2 genuine failures + 1 success, never more
        assert storage.follow_ups.get(fup.id).status == FollowUpStatus.SENT


# --- DISC-8: ghosting can double-signal -------------------------------------


class _AlwaysRaisingApplications:
    """Wraps the real application repo but makes ``update`` always raise --
    simulates the GHOSTED status-flip persistence step being broken."""

    def __init__(self, real):
        self._real = real

    def update(self, app):
        raise RuntimeError("boom: applications.update failed")

    def __getattr__(self, name):
        return getattr(self._real, name)


@pytest.mark.unit
class TestGhostingNoDoubleSignal:
    def test_repeated_flip_failure_never_creates_a_duplicate_signal(self):
        """DISC-8: a permanently-broken status flip means the application
        stays re-matchable and gets re-evaluated by every sweep -- but must
        only ever get ONE ghosting signal recorded for it, not one per
        re-sweep."""
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        app = _app(cid)
        storage.applications.add(app)
        _seed_submitted(storage, app, days_ago=30)
        real_applications = storage.applications
        storage.applications = _AlwaysRaisingApplications(real_applications)
        service = PostSubmissionService(storage)

        first = service.check_ghosting(cid, sla_days=21)
        second = service.check_ghosting(cid, sla_days=21)
        third = service.check_ghosting(cid, sla_days=21)

        # Exactly one signal recorded on the FIRST pass...
        assert len(first) == 1
        # ...and NONE of the re-sweeps add a duplicate, even though the flip
        # keeps failing and the app keeps being re-matched.
        assert second == []
        assert third == []
        assert len(storage.ghosting_signals.list_for_application(app.id)) == 1
        # The app is still stuck un-ghosted (the flip never succeeded).
        assert real_applications.get(app.id).status == ApplicationState.AWAITING_RESPONSE

    def test_flip_recovers_on_a_later_sweep_without_a_duplicate_signal(self):
        """The flip is retried on every re-sweep (not abandoned after the
        first failure) -- once the underlying issue clears, the application
        correctly transitions to GHOSTED, and STILL only one signal total
        exists for it."""
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        app = _app(cid)
        storage.applications.add(app)
        _seed_submitted(storage, app, days_ago=30)
        real_applications = storage.applications
        storage.applications = _AlwaysRaisingApplications(real_applications)
        service = PostSubmissionService(storage)

        first = service.check_ghosting(cid, sla_days=21)
        assert len(first) == 1
        assert real_applications.get(app.id).status == ApplicationState.AWAITING_RESPONSE

        # The underlying problem clears -- restore the real repo.
        storage.applications = real_applications
        second = service.check_ghosting(cid, sla_days=21)

        # No NEW signal was recorded (the one from the first pass still
        # counts), but the flip succeeded this time.
        assert second == []
        assert len(storage.ghosting_signals.list_for_application(app.id)) == 1
        assert real_applications.get(app.id).status == ApplicationState.GHOSTED

    def test_happy_path_single_signal_and_transition_unaffected(self):
        """Control: the ordinary, always-succeeding path is untouched by the
        idempotency guard -- one call, one signal, one transition."""
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        app = _app(cid)
        storage.applications.add(app)
        _seed_submitted(storage, app, days_ago=30)
        service = PostSubmissionService(storage)

        signals = service.check_ghosting(cid, sla_days=21)

        assert len(signals) == 1
        assert storage.applications.get(app.id).status == ApplicationState.GHOSTED
        assert len(storage.ghosting_signals.list_for_application(app.id)) == 1
