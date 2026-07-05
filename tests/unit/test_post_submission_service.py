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
from applicant.application.services.followup_service import FollowUpService
from applicant.application.services.pending_actions_service import PendingActionsService
from applicant.application.services.post_submission_service import (
    DEFAULT_SLA_DAYS,
    KIND_FOLLOWUP_DRAFT,
    KIND_GHOSTING_FLAG,
    PostSubmissionService,
)
from applicant.core.entities.application import Application
from applicant.core.entities.follow_up import FollowUpTemplate
from applicant.core.entities.job_posting import JobPosting
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


# --- dark-engine audit B2 items 8/9/60: the scheduler-driven post-submission
# sweep (ghosting-detection + follow-up-drafting) -----------------------------
#
# Neither ``check_ghosting`` nor ``FollowUpService.draft_followup``/
# ``followup_is_due`` had a real caller before this: the DB tables + service
# methods existed, but nothing ran them on a schedule and nothing surfaced a
# result anywhere reachable. ``run_post_submission_sweep`` is the new single
# entry point the scheduler drives once per (campaign, UTC day); these tests
# pin down that it (a) actually flags/drafts, (b) surfaces BOTH as pending
# actions through the existing Portal substrate (zero new UI), (c) is
# idempotent (dedupes on the application id, not just the UTC day -- re-running
# the sweep never piles up a second open action for the same application), and
# (d) never auto-sends the drafted follow-up or auto-schedules it onto the
# separate send-queue (``FollowUp``/``schedule_follow_up``, item 7 -- explicitly
# out of scope for this wiring).


def _posting(cid, *, company="Acme Corp", title="Senior Engineer"):
    posting = JobPosting(
        id=JobPostingId(new_id()),
        campaign_id=cid,
        title=title,
        company=company,
        source_url="https://acme.example/jobs/1",
    )
    return posting


@pytest.mark.unit
class TestRunPostSubmissionSweep:
    def test_ghosting_flag_materialized_as_pending_action(self):
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        posting = _posting(cid)
        storage.postings.add(posting)
        app = Application(
            id=ApplicationId(new_id()),
            campaign_id=cid,
            posting_id=posting.id,
            status=ApplicationState.AWAITING_RESPONSE,
        )
        storage.applications.add(app)
        _seed_submitted(storage, app, days_ago=30)  # past the 21-day default SLA
        pending = PendingActionsService(storage)
        service = PostSubmissionService(storage, pending_actions=pending)

        result = service.run_post_submission_sweep(cid, now=datetime.now(UTC))

        assert result["ghosted"] == [str(app.id)]
        assert storage.applications.get(app.id).status == ApplicationState.GHOSTED
        actions = [a for a in storage.pending_actions.list_open(cid) if a.kind == KIND_GHOSTING_FLAG]
        assert len(actions) == 1
        assert actions[0].application_id == app.id
        assert "Acme Corp" in actions[0].title

    def test_followup_drafted_when_due_and_never_auto_sent(self):
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        posting = _posting(cid, company="Widgets Inc", title="Data Analyst")
        storage.postings.add(posting)
        app = Application(
            id=ApplicationId(new_id()),
            campaign_id=cid,
            posting_id=posting.id,
            status=ApplicationState.AWAITING_RESPONSE,
        )
        storage.applications.add(app)
        # 15 days: past the 10-day follow-up-due window, but well within the
        # 21-day ghosting SLA -- this app must be DRAFTED, not ghosted.
        _seed_submitted(storage, app, days_ago=15)
        pending = PendingActionsService(storage)
        notifier = _DecisionSpy()
        service = PostSubmissionService(storage, notifier, pending_actions=pending)

        result = service.run_post_submission_sweep(cid, now=datetime.now(UTC))

        assert result["ghosted"] == []
        assert result["followups_drafted"] == [str(app.id)]
        assert storage.applications.get(app.id).status == ApplicationState.AWAITING_RESPONSE

        drafts = [a for a in storage.pending_actions.list_open(cid) if a.kind == KIND_FOLLOWUP_DRAFT]
        assert len(drafts) == 1
        draft = drafts[0]
        assert draft.application_id == app.id
        assert "Widgets Inc" in draft.title
        body = draft.payload.get("body", "")
        assert "Data Analyst" in body
        assert "Widgets Inc" in body

        # Never auto-sent: no notification fired, and nothing was queued onto the
        # SEPARATE scheduled send-queue (FollowUp/schedule_follow_up, item 7 --
        # out of scope here).
        assert notifier.calls == []
        assert storage.follow_ups.list_for_application(app.id) == []

    def test_not_yet_due_is_a_noop(self):
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        app = _app(cid, status=ApplicationState.AWAITING_RESPONSE)
        storage.applications.add(app)
        _seed_submitted(storage, app, days_ago=2)  # well under the 10-day due window
        pending = PendingActionsService(storage)
        service = PostSubmissionService(storage, pending_actions=pending)

        result = service.run_post_submission_sweep(cid, now=datetime.now(UTC))

        assert result == {"ghosted": [], "followups_drafted": []}
        assert storage.pending_actions.list_open(cid) == []

    def test_sweep_is_idempotent_running_twice_creates_no_duplicate_actions(self):
        """Re-running the sweep (same day or not) must never open a SECOND
        ghosting-flag / follow-up-draft pending action for the same application --
        the dedup key is the application id, not the UTC day (unlike the
        Scheduler's own once-per-day guard, which is defense in depth only)."""
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        ghost_posting = _posting(cid, company="GhostCo")
        storage.postings.add(ghost_posting)
        ghost_app = Application(
            id=ApplicationId(new_id()),
            campaign_id=cid,
            posting_id=ghost_posting.id,
            status=ApplicationState.AWAITING_RESPONSE,
        )
        storage.applications.add(ghost_app)
        _seed_submitted(storage, ghost_app, days_ago=30)

        draft_posting = _posting(cid, company="DraftCo")
        storage.postings.add(draft_posting)
        draft_app = Application(
            id=ApplicationId(new_id()),
            campaign_id=cid,
            posting_id=draft_posting.id,
            status=ApplicationState.AWAITING_RESPONSE,
        )
        storage.applications.add(draft_app)
        _seed_submitted(storage, draft_app, days_ago=15)

        pending = PendingActionsService(storage)
        service = PostSubmissionService(storage, pending_actions=pending)
        now = datetime.now(UTC)

        first = service.run_post_submission_sweep(cid, now=now)
        second = service.run_post_submission_sweep(cid, now=now + timedelta(minutes=1))

        # The ghosted app already transitioned away from AWAITING_RESPONSE/
        # POST_SUBMISSION on the first pass, so check_ghosting naturally excludes
        # it the second time; the draft app is still AWAITING_RESPONSE + still due,
        # so the SECOND pass re-considers it -- but ``materialize``'s dedup_key
        # must still yield exactly ONE open pending action per kind.
        assert first["ghosted"] == [str(ghost_app.id)]
        assert second["ghosted"] == []
        assert second["followups_drafted"] == [str(draft_app.id)]

        ghost_actions = [a for a in storage.pending_actions.list_open(cid) if a.kind == KIND_GHOSTING_FLAG]
        draft_actions = [a for a in storage.pending_actions.list_open(cid) if a.kind == KIND_FOLLOWUP_DRAFT]
        assert len(ghost_actions) == 1
        assert len(draft_actions) == 1

    def test_no_pending_actions_collaborator_degrades_silently(self):
        """Every EXISTING caller of ``check_ghosting``/``draft_followup`` (before
        this sweep) constructs ``PostSubmissionService`` with no ``pending_actions``
        -- the sweep must not crash when it's absent, it just can't surface
        anything (nothing to materialize through)."""
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        app = _app(cid, status=ApplicationState.AWAITING_RESPONSE)
        storage.applications.add(app)
        _seed_submitted(storage, app, days_ago=30)
        service = PostSubmissionService(storage)  # no pending_actions

        result = service.run_post_submission_sweep(cid, now=datetime.now(UTC))

        # check_ghosting itself is unaffected -- the app still transitions.
        assert result["ghosted"] == [str(app.id)]
        assert storage.applications.get(app.id).status == ApplicationState.GHOSTED

    def test_ghosting_failure_does_not_block_followup_drafting(self):
        """Best-effort: a broken ``check_ghosting`` (defensive guard inside the
        sweep) must not prevent the follow-up-drafting pass from still running for
        the SAME campaign."""
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        app = _app(cid, status=ApplicationState.AWAITING_RESPONSE)
        storage.applications.add(app)
        _seed_submitted(storage, app, days_ago=15)
        pending = PendingActionsService(storage)
        service = PostSubmissionService(storage, pending_actions=pending)

        def _boom(*a, **k):
            raise RuntimeError("storage exploded")

        service.check_ghosting = _boom  # simulate a broken ghosting pass

        result = service.run_post_submission_sweep(cid, now=datetime.now(UTC))

        assert result["ghosted"] == []
        assert result["followups_drafted"] == [str(app.id)]

    def test_followup_service_due_window_is_configurable(self):
        """A custom ``FollowUpService(due_after_days=...)`` collaborator changes
        the sweep's due window (no hardcoded threshold)."""
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        app = _app(cid, status=ApplicationState.AWAITING_RESPONSE)
        storage.applications.add(app)
        _seed_submitted(storage, app, days_ago=4)  # under the default 10-day window
        pending = PendingActionsService(storage)
        service = PostSubmissionService(
            storage, pending_actions=pending, followup=FollowUpService(due_after_days=3)
        )

        result = service.run_post_submission_sweep(cid, now=datetime.now(UTC))

        assert result["followups_drafted"] == [str(app.id)]
