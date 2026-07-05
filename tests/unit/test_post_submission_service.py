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
from applicant.core.entities.follow_up import FollowUpStatus, FollowUpTemplate
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
        # lens 10 #53: the notification is a product-voice "a draft is ready"
        # prompt, NOT the raw first-person follow-up subject (which would buzz
        # the user's phone reading as if the product were thanking them).
        assert call["title"] != fup.subject
        assert "review & send" in call["title"]
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


# ---------------------------------------------------------------------------
# Dark-engine audit B2 item 7: approve + schedule a drafted follow-up, and the
# send-queue's idempotency / hard-safety guarantees.
# ---------------------------------------------------------------------------


def _seed_draft(storage, pending, app, *, subject="Checking in", body="Hi there") -> None:
    """Materialize a ``followup_draft`` pending action exactly like
    ``PostSubmissionService._draft_followup_if_due`` does, without needing a
    full sweep run (keeps these tests focused on the approve path)."""
    pending.materialize(
        app.campaign_id,
        KIND_FOLLOWUP_DRAFT,
        f"Follow-up ready to review: {app.id}",
        application_id=app.id,
        payload={"subject": subject, "body": body, "days_since_submission": 12},
        dedup_key=f"{KIND_FOLLOWUP_DRAFT}:{app.id}",
    )


@pytest.mark.unit
class TestApproveFollowUpDraft:
    def test_approve_schedules_the_draft_and_resolves_the_pending_action(self):
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        app = _app(cid, status=ApplicationState.AWAITING_RESPONSE)
        storage.applications.add(app)
        pending = PendingActionsService(storage)
        _seed_draft(storage, pending, app, subject="Checking in", body="Hi, following up.")
        service = PostSubmissionService(storage, pending_actions=pending)

        fup = service.approve_follow_up_draft(app.id)

        assert fup is not None
        assert fup.subject == "Checking in"
        assert fup.body == "Hi, following up."
        assert fup.application_id == app.id
        # This is the ONLY producer of the send-queue row -- confirm it landed.
        assert [f.id for f in storage.follow_ups.list_for_application(app.id)] == [fup.id]
        # The originating draft is resolved -- it drops off the Portal.
        drafts = [a for a in storage.pending_actions.list_open(cid) if a.kind == KIND_FOLLOWUP_DRAFT]
        assert drafts == []

    def test_approve_lets_the_owner_edit_subject_and_body_before_scheduling(self):
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        app = _app(cid, status=ApplicationState.AWAITING_RESPONSE)
        storage.applications.add(app)
        pending = PendingActionsService(storage)
        _seed_draft(storage, pending, app, subject="Original subject", body="Original body")
        service = PostSubmissionService(storage, pending_actions=pending)

        fup = service.approve_follow_up_draft(
            app.id, subject="Edited subject", body="Edited body"
        )

        assert fup.subject == "Edited subject"
        assert fup.body == "Edited body"

    def test_approve_returns_none_when_no_draft_exists(self):
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        app = _app(cid, status=ApplicationState.AWAITING_RESPONSE)
        storage.applications.add(app)
        pending = PendingActionsService(storage)  # nothing materialized
        service = PostSubmissionService(storage, pending_actions=pending)

        assert service.approve_follow_up_draft(app.id) is None
        assert storage.follow_ups.list_for_application(app.id) == []

    def test_approve_returns_none_without_a_pending_actions_collaborator(self):
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        app = _app(cid, status=ApplicationState.AWAITING_RESPONSE)
        storage.applications.add(app)
        service = PostSubmissionService(storage)  # no pending_actions

        assert service.approve_follow_up_draft(app.id) is None

    def test_approve_returns_none_for_unknown_application(self):
        storage = InMemoryStorage()
        pending = PendingActionsService(storage)
        service = PostSubmissionService(storage, pending_actions=pending)

        assert service.approve_follow_up_draft(ApplicationId(new_id())) is None

    def test_approving_the_same_draft_twice_only_schedules_once(self):
        """The second approve tap 404s (in the router) because the pending
        action is already resolved -- at the service layer this means a
        second call finds no OPEN draft and returns ``None`` without creating
        a second ``FollowUp``."""
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        app = _app(cid, status=ApplicationState.AWAITING_RESPONSE)
        storage.applications.add(app)
        pending = PendingActionsService(storage)
        _seed_draft(storage, pending, app)
        service = PostSubmissionService(storage, pending_actions=pending)

        first = service.approve_follow_up_draft(app.id)
        second = service.approve_follow_up_draft(app.id)

        assert first is not None
        assert second is None
        assert len(storage.follow_ups.list_for_application(app.id)) == 1


@pytest.mark.unit
class TestSendScheduledFollowUpsHardSafetyAndIdempotency:
    def test_a_drafted_but_unapproved_followup_is_never_sent(self):
        """HARD SAFETY: a ``followup_draft`` pending action alone (never
        approved) must never reach the send queue -- ``schedule_follow_up`` is
        the ONLY producer of a ``follow_ups`` row, and nothing but
        ``approve_follow_up_draft`` ever calls it."""
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        app = _app(cid, status=ApplicationState.AWAITING_RESPONSE)
        storage.applications.add(app)
        pending = PendingActionsService(storage)
        _seed_draft(storage, pending, app)
        spy = _DecisionSpy()
        service = PostSubmissionService(storage, spy, pending_actions=pending)

        sent = service.send_scheduled_follow_ups()

        assert sent == []
        assert spy.calls == []

    def test_a_sent_follow_up_is_never_sent_twice(self):
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        app = _app(cid)
        storage.applications.add(app)
        spy = _DecisionSpy()
        service = PostSubmissionService(storage, notification_service=spy)
        fup = service.schedule_follow_up(
            app.id, template=FollowUpTemplate.CHECK_IN, delay_hours=-1
        )

        first = service.send_scheduled_follow_ups()
        second = service.send_scheduled_follow_ups()

        assert [f.id for f in first] == [fup.id]
        assert second == []
        assert len(spy.calls) == 1, "the follow-up must be notified exactly once"

    def test_send_marks_the_follow_up_sent_with_a_timestamp(self):
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        app = _app(cid)
        storage.applications.add(app)
        service = PostSubmissionService(storage, notification_service=_DecisionSpy())
        fup = service.schedule_follow_up(
            app.id, template=FollowUpTemplate.CHECK_IN, delay_hours=-1
        )

        now = datetime.now(UTC)
        service.send_scheduled_follow_ups(now=now)

        updated = storage.follow_ups.get(fup.id)
        assert updated.status == FollowUpStatus.SENT
        assert updated.sent_at == now

    def test_end_to_end_approve_then_schedule_then_send_once(self):
        """The full item-7 chain: draft -> approve -> due -> sent once."""
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        app = _app(cid, status=ApplicationState.AWAITING_RESPONSE)
        storage.applications.add(app)
        pending = PendingActionsService(storage)
        _seed_draft(storage, pending, app, subject="Checking in", body="Hi.")
        spy = _DecisionSpy()
        service = PostSubmissionService(storage, spy, pending_actions=pending)

        fup = service.approve_follow_up_draft(app.id, delay_hours=-1)  # already due
        sent_first = service.send_scheduled_follow_ups()
        sent_second = service.send_scheduled_follow_ups()

        assert [f.id for f in sent_first] == [fup.id]
        assert sent_second == []
        assert len(spy.calls) == 1
        # lens 10 #53: product-voice "draft ready" title, not the raw subject.
        assert spy.calls[0]["title"] != "Checking in"
        assert "review & send" in spy.calls[0]["title"]
        assert spy.calls[0]["body"] == "Hi."
        assert storage.applications.get(app.id).status == ApplicationState.FOLLOWING_UP


# ---------------------------------------------------------------------------
# Dark-engine audit B2 item 10: rejection/interview/offer scan of the owner's
# real inbox (never fed to scan_email before this).
# ---------------------------------------------------------------------------


class _FakeWorkspace:
    """Stand-in for ``WorkspacePort`` -- only the two methods this sweep uses."""

    def __init__(self, *, is_available=True, emails=None, raises=False):
        self._is_available = is_available
        self._emails = emails if emails is not None else []
        self._raises = raises
        self.calls = 0

    def available(self):
        return self._is_available

    def recent_emails(self, *, owner=None, limit=20):
        self.calls += 1
        if self._raises:
            raise RuntimeError("workspace unreachable")
        return {"emails": self._emails}


def _awaiting_app(cid, *, company, title="Engineer"):
    posting = _posting(cid, company=company, title=title)
    app = Application(
        id=ApplicationId(new_id()),
        campaign_id=cid,
        posting_id=posting.id,
        status=ApplicationState.AWAITING_RESPONSE,
    )
    return posting, app


@pytest.mark.unit
class TestScanInboxForOutcomes:
    def test_no_workspace_wired_is_a_noop(self):
        storage = InMemoryStorage()
        service = PostSubmissionService(storage)  # no workspace

        result = service.scan_inbox_for_outcomes(CampaignId(new_id()))

        assert result == {"scanned": 0, "matched": 0, "outcomes": []}

    def test_workspace_unavailable_is_a_noop(self):
        storage = InMemoryStorage()
        ws = _FakeWorkspace(is_available=False)
        service = PostSubmissionService(storage, workspace=ws)

        result = service.scan_inbox_for_outcomes(CampaignId(new_id()))

        assert result == {"scanned": 0, "matched": 0, "outcomes": []}
        assert ws.calls == 0  # never even asked for emails once disabled

    def test_workspace_read_failure_degrades_to_noop(self):
        storage = InMemoryStorage()
        ws = _FakeWorkspace(raises=True)
        service = PostSubmissionService(storage, workspace=ws)

        result = service.scan_inbox_for_outcomes(CampaignId(new_id()))

        assert result == {"scanned": 0, "matched": 0, "outcomes": []}

    def test_empty_inbox_is_a_noop(self):
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        posting, app = _awaiting_app(cid, company="Acme Corp")
        storage.postings.add(posting)
        storage.applications.add(app)
        ws = _FakeWorkspace(emails=[])
        service = PostSubmissionService(storage, workspace=ws)

        result = service.scan_inbox_for_outcomes(cid)

        assert result == {"scanned": 0, "matched": 0, "outcomes": []}

    def test_email_matching_exactly_one_company_records_a_rejection(self):
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        posting, app = _awaiting_app(cid, company="Acme Corp")
        storage.postings.add(posting)
        storage.applications.add(app)
        ws = _FakeWorkspace(
            emails=[
                {
                    "subject": "Update on your Acme Corp application",
                    "from": "recruiting@acme.example",
                    # 3 keyword hits (>= the 0.8 auto-record confidence
                    # threshold): "unfortunately" + "not moving forward" +
                    # "other candidates".
                    "body": (
                        "Unfortunately, after careful consideration we are not "
                        "moving forward with your application. We have decided "
                        "to proceed with other candidates for this role."
                    ),
                }
            ]
        )
        service = PostSubmissionService(storage, workspace=ws)

        result = service.scan_inbox_for_outcomes(cid)

        assert result["scanned"] == 1
        assert result["matched"] == 1
        assert result["outcomes"][0]["application_id"] == str(app.id)
        assert result["outcomes"][0]["outcome_type"] == "rejected"
        assert storage.applications.get(app.id).status == ApplicationState.REJECTED

    def test_ambiguous_company_match_across_two_applications_is_skipped(self):
        """Two in-flight applications share a company name -- the email can't
        be attributed to one over the other, so NEITHER is touched."""
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        posting1, app1 = _awaiting_app(cid, company="Acme Corp", title="Engineer")
        posting2, app2 = _awaiting_app(cid, company="Acme Corp", title="Designer")
        storage.postings.add(posting1)
        storage.postings.add(posting2)
        storage.applications.add(app1)
        storage.applications.add(app2)
        ws = _FakeWorkspace(
            emails=[
                {
                    "subject": "Update on your Acme Corp application",
                    "from": "recruiting@acme.example",
                    "body": "Unfortunately, we will not be moving forward.",
                }
            ]
        )
        service = PostSubmissionService(storage, workspace=ws)

        result = service.scan_inbox_for_outcomes(cid)

        assert result == {"scanned": 0, "matched": 0, "outcomes": []}
        assert storage.applications.get(app1.id).status == ApplicationState.AWAITING_RESPONSE
        assert storage.applications.get(app2.id).status == ApplicationState.AWAITING_RESPONSE

    def test_email_matching_no_company_is_skipped(self):
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        posting, app = _awaiting_app(cid, company="Acme Corp")
        storage.postings.add(posting)
        storage.applications.add(app)
        ws = _FakeWorkspace(
            emails=[{"subject": "Newsletter", "from": "news@example.com", "body": "Hello!"}]
        )
        service = PostSubmissionService(storage, workspace=ws)

        result = service.scan_inbox_for_outcomes(cid)

        assert result == {"scanned": 0, "matched": 0, "outcomes": []}

    def test_non_matching_email_language_is_scanned_but_not_recorded(self):
        """The company is matched unambiguously but nothing in the email
        confidently triggers a detector -- ``scanned`` counts the attempt,
        ``matched``/``outcomes`` stay empty."""
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        posting, app = _awaiting_app(cid, company="Acme Corp")
        storage.postings.add(posting)
        storage.applications.add(app)
        ws = _FakeWorkspace(
            emails=[
                {
                    "subject": "Acme Corp newsletter",
                    "from": "news@acme.example",
                    "body": "Check out our latest product updates.",
                }
            ]
        )
        service = PostSubmissionService(storage, workspace=ws)

        result = service.scan_inbox_for_outcomes(cid)

        assert result["scanned"] == 1
        assert result["matched"] == 0
        assert result["outcomes"] == []
        assert storage.applications.get(app.id).status == ApplicationState.AWAITING_RESPONSE
