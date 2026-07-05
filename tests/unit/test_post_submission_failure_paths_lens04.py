"""Lens-04 audit regressions (#42/#43/#44) — three bare ``except Exception:
pass``/``continue`` swallow sites in ``PostSubmissionService`` that dropped a
state transition (or a follow-up send failure) with zero log and no bound.

Hermetic: ``InMemoryStorage``, no DB. Each test forces the exact collaborator
call the swallow wraps to raise, then asserts:

1. the failure is now LOGGED (a ``log.warning(..., exc_info=True)`` call with a
   stable event name), matching this module's existing style (see e.g.
   ``post_submission_ghosting_flag_failed``, ``post_submission_followup_mark_
   sent_failed`` elsewhere in the same file); and
2. the failure is OBSERVABLE/BOUNDED rather than silently masquerading as
   success -- the caller never sees a state transition that didn't actually
   persist, and a follow-up notify failure leaves the row retryable (not lost).

Follows the repo's established pattern for asserting on logs (see
``test_material_service.py::test_aggressiveness_persist_failure_degrades_but_
logs``): monkeypatch the module's ``log.warning`` directly rather than
``caplog``, which is documented elsewhere in this suite as order-dependent /
flaky under a full-suite run.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

import applicant.application.services.post_submission_service as post_submission_service_module
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.post_submission_service import PostSubmissionService
from applicant.core.entities.application import Application
from applicant.core.entities.follow_up import FollowUpStatus, FollowUpTemplate
from applicant.core.entities.outcome_event import OutcomeEvent
from applicant.core.entities.rejection_signal import RejectionSignal, RejectionSource
from applicant.core.entities.submission_snapshot import SubmissionSnapshot
from applicant.core.ids import (
    ApplicationId,
    CampaignId,
    JobPostingId,
    OutcomeEventId,
    RejectionSignalId,
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


def _seed_submitted(storage, app, *, days_ago: float) -> None:
    storage.outcomes.add(
        OutcomeEvent(id=OutcomeEventId(new_id()), application_id=app.id, type="submitted")
    )
    captured_at = datetime.now(UTC) - timedelta(days=days_ago)
    storage.submission_snapshots.add(
        SubmissionSnapshot(
            id=SubmissionSnapshotId(new_id()),
            application_id=app.id,
            captured_at=captured_at,
        )
    )


class _RaisingApplications:
    """Wraps the real ``_ApplicationRepo`` but makes ``update`` always raise.

    Every other attribute (``get``, ``list_by_status``, ...) delegates to the
    real in-memory repo via ``__getattr__`` so the rest of each flow behaves
    exactly as it does with the real storage.
    """

    def __init__(self, real):
        self._real = real

    def update(self, app):
        raise RuntimeError("boom: applications.update failed")

    def __getattr__(self, name):
        return getattr(self._real, name)


class _RaisingNotifier:
    """Notification-service double whose ``notify_decision`` always raises --
    simulates a Discord/push/email delivery outage during follow-up send."""

    def notify_decision(self, decision_ref, *, title, body, deep_link=None):
        raise RuntimeError("boom: notify_decision failed")


def _install_log_spy(monkeypatch):
    recorded: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        post_submission_service_module.log,
        "warning",
        lambda msg, *a, **k: recorded.append((msg, k)),
    )
    return recorded


def _find(recorded, event_name):
    return next((kwargs for msg, kwargs in recorded if msg == event_name), None)


@pytest.mark.unit
class TestDetectOutcomeTransitionSwallow:
    """#42: the REJECTED transition + outcome emission was ``try/except: pass``."""

    def test_transition_failure_is_logged_and_not_reported_as_success(self, monkeypatch):
        recorded = _install_log_spy(monkeypatch)
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        app = _app(cid, status=ApplicationState.AWAITING_RESPONSE)
        storage.applications.add(app)
        real_applications = storage.applications
        storage.applications = _RaisingApplications(real_applications)
        service = PostSubmissionService(storage)
        signal = RejectionSignal(
            id=RejectionSignalId(new_id()),
            application_id=app.id,
            source=RejectionSource.EMAIL,
            signal_text="Unfortunately, we will not be proceeding",
            confidence=1.0,
        )

        result = service.detect_outcome(app.id, rejection_signals=[signal])

        # The failed transition must NEVER be reported to the caller as if it
        # had succeeded -- the returned application must still read its
        # ORIGINAL (unmutated) status, not REJECTED.
        assert result is not None
        assert result.status == ApplicationState.AWAITING_RESPONSE
        # And the real backing store must agree -- no partial/ghost update.
        assert real_applications.get(app.id).status == ApplicationState.AWAITING_RESPONSE

        kwargs = _find(recorded, "post_submission_rejection_transition_failed")
        assert kwargs is not None, "the swallow must now log a stable event name"
        assert kwargs.get("application_id") == str(app.id)
        assert kwargs.get("exc_info") is True

    def test_successful_transition_is_unaffected_and_logs_nothing(self, monkeypatch):
        """Control: the happy path is untouched by the logging addition."""
        recorded = _install_log_spy(monkeypatch)
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        app = _app(cid, status=ApplicationState.AWAITING_RESPONSE)
        storage.applications.add(app)
        service = PostSubmissionService(storage)
        signal = RejectionSignal(
            id=RejectionSignalId(new_id()),
            application_id=app.id,
            source=RejectionSource.EMAIL,
            signal_text="Unfortunately, we will not be proceeding",
            confidence=1.0,
        )

        result = service.detect_outcome(app.id, rejection_signals=[signal])

        assert result.status == ApplicationState.REJECTED
        assert storage.applications.get(app.id).status == ApplicationState.REJECTED
        assert _find(recorded, "post_submission_rejection_transition_failed") is None


@pytest.mark.unit
class TestCheckGhostingTransitionSwallow:
    """#43: the GHOSTED transition + outcome emission was ``try/except: pass``."""

    def test_transition_failure_is_logged_and_state_stays_unghosted(self, monkeypatch):
        recorded = _install_log_spy(monkeypatch)
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        app = _app(cid, status=ApplicationState.AWAITING_RESPONSE)
        storage.applications.add(app)
        _seed_submitted(storage, app, days_ago=30)
        real_applications = storage.applications
        storage.applications = _RaisingApplications(real_applications)
        service = PostSubmissionService(storage)

        signals = service.check_ghosting(cid, sla_days=21)

        # The ghosting SIGNAL is (and always was) persisted before the guarded
        # transition -- that part must be unaffected.
        assert len(signals) == 1
        assert storage.ghosting_signals.list_for_application(app.id)
        # But the application must NOT silently read as GHOSTED when the
        # transition itself failed.
        assert real_applications.get(app.id).status == ApplicationState.AWAITING_RESPONSE

        kwargs = _find(recorded, "post_submission_ghosting_transition_failed")
        assert kwargs is not None, "the swallow must now log a stable event name"
        assert kwargs.get("application_id") == str(app.id)
        assert kwargs.get("exc_info") is True

    def test_successful_transition_is_unaffected_and_logs_nothing(self, monkeypatch):
        recorded = _install_log_spy(monkeypatch)
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        app = _app(cid, status=ApplicationState.AWAITING_RESPONSE)
        storage.applications.add(app)
        _seed_submitted(storage, app, days_ago=30)
        service = PostSubmissionService(storage)

        signals = service.check_ghosting(cid, sla_days=21)

        assert len(signals) == 1
        assert storage.applications.get(app.id).status == ApplicationState.GHOSTED
        assert _find(recorded, "post_submission_ghosting_transition_failed") is None


@pytest.mark.unit
class TestSendScheduledFollowUpsSwallows:
    """#44: the notifier ``except Exception: continue`` had NO log at all, and
    the separate FOLLOWING_UP state-advance was ``try/except: pass``."""

    def test_notify_failure_is_logged_and_follow_up_stays_retryable(self, monkeypatch):
        recorded = _install_log_spy(monkeypatch)
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        app = _app(cid, status=ApplicationState.AWAITING_RESPONSE)
        storage.applications.add(app)
        service = PostSubmissionService(storage, notification_service=_RaisingNotifier())
        fup = service.schedule_follow_up(
            app.id,
            template=FollowUpTemplate.CHECK_IN,
            delay_hours=-1,  # already due
        )

        now = datetime.now(UTC)
        sent = service.send_scheduled_follow_ups(now=now)

        # Never silently marked sent -- a lost notification must not be
        # reported as a successful send.
        assert sent == []
        stored_fup = storage.follow_ups.get(fup.id)
        assert stored_fup.status == FollowUpStatus.SCHEDULED
        # Bounded, not lost: the row is still due and will be retried the very
        # next tick (the existing ``list_due`` contract), never silently
        # dropped and never retried in an unbounded hot loop within this call.
        assert fup.id in [f.id for f in storage.follow_ups.list_due(now)]
        # The application must not have advanced either -- nothing was sent.
        assert storage.applications.get(app.id).status == ApplicationState.AWAITING_RESPONSE

        kwargs = _find(recorded, "post_submission_followup_notify_failed")
        assert kwargs is not None, "the swallow must now log a stable event name"
        assert kwargs.get("follow_up_id") == str(fup.id)
        assert kwargs.get("exc_info") is True

    def test_state_advance_failure_is_logged_but_follow_up_still_marked_sent(self, monkeypatch):
        recorded = _install_log_spy(monkeypatch)
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        app = _app(cid, status=ApplicationState.AWAITING_RESPONSE)
        storage.applications.add(app)

        class _DecisionSpy:
            def notify_decision(self, decision_ref, *, title, body, deep_link=None):
                return "handle"

        service = PostSubmissionService(storage, notification_service=_DecisionSpy())
        fup = service.schedule_follow_up(
            app.id,
            template=FollowUpTemplate.CHECK_IN,
            delay_hours=-1,
        )
        # Only make the APPLICATION status-advance fail -- the follow-up
        # notify above already succeeded and ``follow_ups.update`` (a
        # different repo) is untouched, so the "mark SENT" step still works.
        storage.applications = _RaisingApplications(storage.applications)

        now = datetime.now(UTC)
        sent = service.send_scheduled_follow_ups(now=now)

        # The follow-up itself WAS sent (notified + marked SENT) -- that part
        # of the flow is independent of the application status-advance and
        # must not regress because of this fix.
        assert [f.id for f in sent] == [fup.id]
        assert storage.follow_ups.get(fup.id).status == FollowUpStatus.SENT

        kwargs = _find(recorded, "post_submission_followup_state_advance_failed")
        assert kwargs is not None, "the swallow must now log a stable event name"
        assert kwargs.get("follow_up_id") == str(fup.id)
        assert kwargs.get("application_id") == str(app.id)
        assert kwargs.get("exc_info") is True

    def test_happy_path_logs_neither_swallow_event(self, monkeypatch):
        """Control: a fully successful send touches neither new log line."""
        recorded = _install_log_spy(monkeypatch)
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        app = _app(cid, status=ApplicationState.AWAITING_RESPONSE)
        storage.applications.add(app)

        class _DecisionSpy:
            def notify_decision(self, decision_ref, *, title, body, deep_link=None):
                return "handle"

        service = PostSubmissionService(storage, notification_service=_DecisionSpy())
        service.schedule_follow_up(app.id, template=FollowUpTemplate.CHECK_IN, delay_hours=-1)

        service.send_scheduled_follow_ups()

        assert storage.applications.get(app.id).status == ApplicationState.FOLLOWING_UP
        assert _find(recorded, "post_submission_followup_notify_failed") is None
        assert _find(recorded, "post_submission_followup_state_advance_failed") is None
