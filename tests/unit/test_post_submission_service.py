"""PostSubmissionService unit tests — regression coverage for post-submission bugs.

Hermetic: InMemoryStorage, no DB/browser. These pin down three fixes:

* ``send_scheduled_follow_ups`` now calls the REAL ``NotificationService
  .notify_decision(...)`` (it used to call a nonexistent ``.notify(...)`` that
  raised ``AttributeError``, silently swallowed by the surrounding
  ``try/except``, so the follow-up was neither sent nor state-transitioned);
* ``_submission_age`` now looks up the real submission-snapshot timestamp
  instead of hardcoding ``timedelta(0)`` (so ``check_ghosting`` could never
  actually flag anything as ghosted);
* the ghosting SLA constant lives once on this module (see
  ``test_silence_service.py`` for the cross-module unification check).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.post_submission_service import (
    DEFAULT_SLA_DAYS,
    PostSubmissionService,
)
from applicant.core.entities.application import Application
from applicant.core.entities.follow_up import FollowUpTemplate
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
        root_url="https://acme.myworkdayjobs.com/job/1",
    )


class _DecisionSpy:
    """Spy for the notification-service collaborator.

    Deliberately exposes ONLY ``notify_decision`` (the real method on
    ``NotificationService``) — if ``send_scheduled_follow_ups`` regressed to
    calling a nonexistent ``.notify(...)`` again, that call would raise
    ``AttributeError`` on this spy (swallowed by the service's own
    try/except, but surfacing as an empty ``calls`` list / no state change,
    which the assertions below catch).
    """

    def __init__(self):
        self.calls: list[dict] = []

    def notify_decision(self, decision_ref, *, title, body, deep_link=None):
        self.calls.append(
            {
                "decision_ref": decision_ref,
                "title": title,
                "body": body,
                "deep_link": deep_link,
            }
        )
        return "handle"


def _seed_submitted(storage, app, *, days_ago: float | None) -> None:
    """Record a 'submitted' outcome event and (optionally) a snapshot."""
    storage.outcomes.add(
        OutcomeEvent(id=OutcomeEventId(new_id()), application_id=app.id, type="submitted")
    )
    if days_ago is not None:
        captured_at = datetime.now(UTC) - timedelta(days=days_ago)
        storage.submission_snapshots.add(
            SubmissionSnapshot(
                id=SubmissionSnapshotId(new_id()),
                application_id=app.id,
                captured_at=captured_at,
            )
        )


@pytest.mark.unit
class TestSendScheduledFollowUps:
    def test_due_follow_up_notifies_via_notify_decision(self):
        # Regression: send_scheduled_follow_ups used to call the nonexistent
        # NotificationService.notify(...) — AttributeError, silently swallowed,
        # so nothing was ever actually sent. It must now call notify_decision.
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        app = _app(cid)
        storage.applications.add(app)
        spy = _DecisionSpy()
        service = PostSubmissionService(storage, notification_service=spy)

        fup = service.schedule_follow_up(
            app.id,
            template=FollowUpTemplate.CHECK_IN,
            delay_hours=-1,  # already due
            subject="Checking in on my application",
            body="I wanted to check in on the status of my application.",
        )

        sent = service.send_scheduled_follow_ups()

        assert [f.id for f in sent] == [fup.id]
        assert len(spy.calls) == 1, "notify_decision must be called exactly once"
        call = spy.calls[0]
        assert call["decision_ref"] == str(fup.id)
        assert call["title"] == fup.subject
        assert call["body"] == fup.body
        assert call["deep_link"] == f"/applications/{fup.application_id}"

    def test_successful_send_transitions_application_to_following_up(self):
        # After a successful send the APPLICATION moves AWAITING_RESPONSE ->
        # FOLLOWING_UP (the FollowUp entity itself has no persisted status
        # update in this storage adapter — the application is the durable
        # signal that the follow-up went out).
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        app = _app(cid, status=ApplicationState.AWAITING_RESPONSE)
        storage.applications.add(app)
        spy = _DecisionSpy()
        service = PostSubmissionService(storage, notification_service=spy)
        service.schedule_follow_up(
            app.id, template=FollowUpTemplate.THANK_YOU, delay_hours=-1
        )

        service.send_scheduled_follow_ups()

        updated = storage.applications.get(app.id)
        assert updated.status == ApplicationState.FOLLOWING_UP

    def test_send_scheduled_follow_ups_does_not_raise(self):
        # Before the fix, the nonexistent `.notify(...)` call raised
        # AttributeError on every real NotificationService; this must complete
        # cleanly with a real spy that only implements notify_decision.
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        app = _app(cid)
        storage.applications.add(app)
        service = PostSubmissionService(storage, notification_service=_DecisionSpy())
        service.schedule_follow_up(
            app.id, template=FollowUpTemplate.CHECK_IN, delay_hours=-1
        )
        service.send_scheduled_follow_ups()  # must not raise

    def test_no_due_follow_ups_is_a_noop(self):
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        app = _app(cid)
        storage.applications.add(app)
        spy = _DecisionSpy()
        service = PostSubmissionService(storage, notification_service=spy)
        service.schedule_follow_up(
            app.id, template=FollowUpTemplate.CHECK_IN, delay_hours=999
        )  # far in the future, not due

        sent = service.send_scheduled_follow_ups()

        assert sent == []
        assert spy.calls == []
        assert storage.applications.get(app.id).status == ApplicationState.AWAITING_RESPONSE


@pytest.mark.unit
class TestSubmissionAge:
    def test_computes_real_elapsed_time_not_zero(self):
        # Regression: _submission_age used to hardcode timedelta(0).
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        app = _app(cid)
        storage.applications.add(app)
        _seed_submitted(storage, app, days_ago=10)
        service = PostSubmissionService(storage)

        age = service._submission_age(app, datetime.now(UTC))

        assert age is not None
        assert age != timedelta(0)
        assert 9 <= age.days <= 10

    def test_returns_none_when_no_snapshot_exists(self):
        # A 'submitted' outcome exists but no snapshot was ever captured for it
        # -> degrade gracefully (None), not a crash and not timedelta(0).
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        app = _app(cid)
        storage.applications.add(app)
        _seed_submitted(storage, app, days_ago=None)  # no snapshot
        service = PostSubmissionService(storage)

        assert service._submission_age(app, datetime.now(UTC)) is None

    def test_returns_none_when_never_submitted(self):
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        app = _app(cid)
        storage.applications.add(app)
        service = PostSubmissionService(storage)

        assert service._submission_age(app, datetime.now(UTC)) is None


@pytest.mark.unit
class TestCheckGhosting:
    def test_flags_application_once_age_crosses_sla(self):
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        app = _app(cid, status=ApplicationState.AWAITING_RESPONSE)
        storage.applications.add(app)
        _seed_submitted(storage, app, days_ago=30)
        service = PostSubmissionService(storage)

        signals = service.check_ghosting(cid, sla_days=21)

        assert len(signals) == 1
        assert signals[0].application_id == app.id
        assert signals[0].submission_age_days >= 21
        updated = storage.applications.get(app.id)
        assert updated.status == ApplicationState.GHOSTED
        assert storage.ghosting_signals.list_for_application(app.id)

    def test_does_not_flag_when_still_within_sla(self):
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        app = _app(cid, status=ApplicationState.AWAITING_RESPONSE)
        storage.applications.add(app)
        _seed_submitted(storage, app, days_ago=3)
        service = PostSubmissionService(storage)

        signals = service.check_ghosting(cid, sla_days=DEFAULT_SLA_DAYS)

        assert signals == []
        assert storage.applications.get(app.id).status == ApplicationState.AWAITING_RESPONSE

    def test_degrades_gracefully_when_no_snapshot(self):
        # No submission snapshot recorded -> _submission_age is None -> the app
        # is simply skipped, not crashed and not falsely flagged.
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        app = _app(cid, status=ApplicationState.AWAITING_RESPONSE)
        storage.applications.add(app)
        _seed_submitted(storage, app, days_ago=None)
        service = PostSubmissionService(storage)

        signals = service.check_ghosting(cid, sla_days=1)

        assert signals == []
        assert storage.applications.get(app.id).status == ApplicationState.AWAITING_RESPONSE


# --- tracker board (design-audit Top-25 #4) ---------------------------------
#
# Round 2 wires PostSubmissionService to a new front-door router/proxy/surface.
# These pin down the two additions that back it: a pure read (list_tracker_rows)
# and the owner-triggered manual write (record_manual_outcome).


@pytest.mark.unit
class TestListTrackerRows:
    def test_lists_only_tracker_states_newest_first(self):
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        early_stage = _app(cid, status=ApplicationState.PREFILLING)
        awaiting = _app(cid, status=ApplicationState.AWAITING_RESPONSE)
        rejected = _app(cid, status=ApplicationState.REJECTED)
        storage.applications.add(early_stage)
        storage.applications.add(awaiting)
        storage.applications.add(rejected)
        _seed_submitted(storage, awaiting, days_ago=5)
        _seed_submitted(storage, rejected, days_ago=10)
        service = PostSubmissionService(storage)

        rows = service.list_tracker_rows(cid)

        ids = [r["application_id"] for r in rows]
        # The still-prefilling application has nothing to track yet.
        assert str(early_stage.id) not in ids
        assert str(awaiting.id) in ids
        assert str(rejected.id) in ids
        # Newest submission (5 days ago) sorts before the older one (10 days ago).
        assert ids.index(str(awaiting.id)) < ids.index(str(rejected.id))
        awaiting_row = next(r for r in rows if r["application_id"] == str(awaiting.id))
        assert awaiting_row["status"] == "AWAITING_RESPONSE"
        assert awaiting_row["signals"] == []

    def test_positive_signals_layer_onto_the_row_without_changing_status(self):
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        app = _app(cid, status=ApplicationState.AWAITING_RESPONSE)
        storage.applications.add(app)
        _seed_submitted(storage, app, days_ago=2)
        service = PostSubmissionService(storage)

        service.record_manual_outcome(app.id, "interview_invited")
        rows = service.list_tracker_rows(cid)

        row = next(r for r in rows if r["application_id"] == str(app.id))
        assert row["status"] == "AWAITING_RESPONSE"  # unchanged: no §7 state for this
        assert row["signals"] == ["interview_invited"]

    def test_empty_campaign_returns_empty_list(self):
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        service = PostSubmissionService(storage)

        assert service.list_tracker_rows(cid) == []


@pytest.mark.unit
class TestRecordManualOutcome:
    def test_rejected_transitions_status_and_records_manual_event(self):
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        app = _app(cid, status=ApplicationState.AWAITING_RESPONSE)
        storage.applications.add(app)
        service = PostSubmissionService(storage)

        event = service.record_manual_outcome(app.id, "rejected")

        assert event.type == "rejected"
        assert event.source.value == "manual"
        assert storage.applications.get(app.id).status == ApplicationState.REJECTED

    def test_interview_invited_records_event_without_changing_status(self):
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        app = _app(cid, status=ApplicationState.AWAITING_RESPONSE)
        storage.applications.add(app)
        service = PostSubmissionService(storage)

        event = service.record_manual_outcome(app.id, "interview_invited")

        assert event.type == "interview_invited"
        assert event.source.value == "manual"
        # No §7 state exists for "interview invited" -- status is untouched.
        assert storage.applications.get(app.id).status == ApplicationState.AWAITING_RESPONSE

    def test_unrecognized_outcome_type_raises_value_error(self):
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        app = _app(cid, status=ApplicationState.AWAITING_RESPONSE)
        storage.applications.add(app)
        service = PostSubmissionService(storage)

        with pytest.raises(ValueError):
            service.record_manual_outcome(app.id, "not-a-real-outcome")

    def test_unknown_application_returns_none(self):
        storage = InMemoryStorage()
        service = PostSubmissionService(storage)

        assert service.record_manual_outcome(ApplicationId(new_id()), "rejected") is None

    def test_illegal_transition_is_swallowed_but_event_still_recorded(self):
        # ARCHIVED is a terminal §7 state with no outgoing transitions -- a stale
        # "mark rejected" tap on an already-archived application must not raise,
        # and the outcome trail still records that the owner reported it.
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        app = _app(cid, status=ApplicationState.ARCHIVED)
        storage.applications.add(app)
        service = PostSubmissionService(storage)

        event = service.record_manual_outcome(app.id, "rejected")

        assert event.type == "rejected"
        assert storage.applications.get(app.id).status == ApplicationState.ARCHIVED
