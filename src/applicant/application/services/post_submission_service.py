"""PostSubmissionService -- post-submission lifecycle tracking (G16/#190)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from applicant.core.entities.follow_up import FollowUp, FollowUpTemplate
from applicant.core.entities.ghosting_signal import GhostingSignal
from applicant.core.entities.outcome_event import OutcomeEvent, OutcomeSource
from applicant.core.entities.rejection_signal import RejectionSignal, RejectionSource
from applicant.core.events import OutcomeRecorded, event_bus
from applicant.core.ids import (
    FollowUpId,
    OutcomeEventId,
    RejectionSignalId,
    new_id,
)
from applicant.core.state_machine import ApplicationState
from applicant.observability.logging import get_logger

log = get_logger(__name__)
#: Days of total silence after which a submitted application is considered likely
#: ghosted (single source of truth, shared with SilenceService — #192/#190). 14 days
#: is aggressive for large-company pipelines; 30 is defensible but slow to flag a
#: small-company no-response. 21 is the unified middle ground.
DEFAULT_SLA_DAYS = 21
THANK_YOU_DELAY_HOURS = 2
CHECK_IN_DELAY_DAYS = 7


class PostSubmissionService:
    def __init__(self, storage, notification_service=None):
        self._storage = storage
        self._notification = notification_service

    def enter_post_submission(self, application, *, snapshot=None):
        """Transition the application to POST_SUBMISSION.

        The subsequent move to AWAITING_RESPONSE is a SEPARATE lifecycle step
        driven by the tracker/scheduler (advance_to_awaiting_response), NOT
        applied synchronously here.  Doing so synchronously would skip
        SUBMITTED_BY_USER, breaking the mark-submitted contract.
        """
        app = application.with_status(ApplicationState.POST_SUBMISSION)
        self._storage.applications.update(app)
        if snapshot:
            self._storage.submission_snapshots.add(snapshot)
        self._storage.commit()
        return app

    def advance_to_awaiting_response(self, application):
        app = application.with_status(ApplicationState.AWAITING_RESPONSE)
        self._storage.applications.update(app)
        return app

    def poll_status(self, application_id):
        app = self._storage.applications.get(application_id)
        return {"application_id": str(application_id), "status": app.status.value} if app else None

    def detect_outcome(self, application_id, *, rejection_signals=None):
        app = self._storage.applications.get(application_id)
        if app is None:
            return None
        stored = list(self._storage.rejection_signals.list_for_application(application_id))
        if rejection_signals:
            for sig in rejection_signals:
                self._storage.rejection_signals.add(sig)
            stored.extend(rejection_signals)
            self._storage.commit()
        if stored:
            try:
                app = app.with_status(ApplicationState.REJECTED)
                self._storage.applications.update(app)
                self._record_outcome_event(app, "rejected")
                self._storage.commit()
                return app
            except Exception:
                pass
        return app

    def process_rejection_signal(self, application_id, *, source, signal_text="", confidence=1.0, detail=None):
        signal = RejectionSignal(
            id=RejectionSignalId(new_id()),
            application_id=application_id,
            source=source,
            signal_text=signal_text,
            confidence=confidence,
            detail=detail or {},
        )
        self._storage.rejection_signals.add(signal)
        if confidence >= 0.8:
            self.detect_outcome(application_id, rejection_signals=[signal])
        else:
            self._storage.commit()
        return signal

    def scan_email_for_rejection(self, email_subject, email_body, application_id):
        keywords = [
            "unfortunately",
            "regret to inform",
            "not moving forward",
            "other candidates",
            "not selected",
            "position has been filled",
            "will not be proceeding",
        ]
        combined = (email_subject + " " + email_body).lower()
        matched = [kw for kw in keywords if kw in combined]
        if not matched:
            return None
        confidence = min(0.5 + 0.1 * len(matched), 0.95)
        return self.process_rejection_signal(
            application_id,
            source=RejectionSource.EMAIL,
            signal_text="Email matched: " + ", ".join(matched),
            confidence=confidence,
            detail={"subject": email_subject, "matched_keywords": matched},
        )

    def check_ghosting(self, campaign_id, *, sla_days=DEFAULT_SLA_DAYS, now=None):
        now = now or datetime.now(UTC)
        signals = []
        for app in self._storage.applications.list_by_status(
            campaign_id, (ApplicationState.AWAITING_RESPONSE, ApplicationState.POST_SUBMISSION)
        ):
            age = self._submission_age(app, now)
            if age is None or age.days < sla_days:
                continue
            ghost = GhostingSignal(
                campaign_id=campaign_id,
                application_id=app.id,
                sla_days=sla_days,
                submission_age_days=age.days,
                detail={"status": app.status.value, "sla_days": sla_days, "age_days": age.days},
            )
            signals.append(ghost)
            self._storage.ghosting_signals.add(ghost)
            try:
                app = app.with_status(ApplicationState.GHOSTED)
                self._storage.applications.update(app)
                self._record_outcome_event(app, "ghosted")
            except Exception:
                pass
        if signals:
            self._storage.commit()
        return signals

    def _submission_age(self, application, now):
        for ev in self._storage.outcomes.list_for_application(application.id):
            if ev.type == "submitted":
                snapshot = self._storage.submission_snapshots.get_for_application(application.id)
                if snapshot is None:
                    return None
                submitted_at = snapshot.captured_at
                if submitted_at.tzinfo is None:
                    submitted_at = submitted_at.replace(tzinfo=UTC)
                return now - submitted_at
        return None

    def schedule_follow_up(self, application_id, *, template, delay_hours=None, subject="", body=""):
        app = self._storage.applications.get(application_id)
        if app is None:
            raise ValueError(f"Application {application_id} not found")
        now = datetime.now(UTC)
        if delay_hours is None:
            delay_hours = THANK_YOU_DELAY_HOURS if template == FollowUpTemplate.THANK_YOU else CHECK_IN_DELAY_DAYS * 24
        fup = FollowUp(
            id=FollowUpId(new_id()),
            campaign_id=app.campaign_id,
            application_id=application_id,
            template=template,
            subject=subject or self._default_subject(template),
            body=body or self._default_body(template),
            scheduled_at=now + timedelta(hours=delay_hours),
        )
        self._storage.follow_ups.add(fup)
        self._storage.commit()
        return fup

    def send_scheduled_follow_ups(self, now=None):
        now = now or datetime.now(UTC)
        sent = []
        for fup in self._storage.follow_ups.list_due(now):
            if self._notification:
                try:
                    self._notification.notify_decision(
                        str(fup.id),
                        title=fup.subject,
                        body=fup.body,
                        deep_link=f"/applications/{fup.application_id}",
                    )
                except Exception:
                    continue
            sent.append(fup)
            try:
                app = self._storage.applications.get(fup.application_id)
                if app and app.status == ApplicationState.AWAITING_RESPONSE:
                    self._storage.applications.update(app.with_status(ApplicationState.FOLLOWING_UP))
            except Exception:
                pass
        if sent:
            self._storage.commit()
        return sent

    @staticmethod
    def _default_subject(template):
        if template == FollowUpTemplate.THANK_YOU:
            return "Thank you for your time"
        if template == FollowUpTemplate.CHECK_IN:
            return "Checking in on my application"
        if template == FollowUpTemplate.REJECTION_FOLLOW_UP:
            return "Following up on your decision"
        return "Application follow-up"

    @staticmethod
    def _default_body(template):
        if template == FollowUpTemplate.THANK_YOU:
            return "Thank you for the opportunity to apply. I look forward to hearing about next steps."
        if template == FollowUpTemplate.CHECK_IN:
            return "I wanted to check in on the status of my application. Please let me know if you need any additional information."
        if template == FollowUpTemplate.REJECTION_FOLLOW_UP:
            return "I understand the position may not be a fit, but I would appreciate any feedback you could share."
        return ""

    def archive(self, application_id):
        app = self._storage.applications.get(application_id)
        if app is None:
            return None
        try:
            app = app.with_status(ApplicationState.ARCHIVED)
            self._storage.applications.update(app)
            self._storage.commit()
            return app
        except Exception:
            return None

    def _record_outcome_event(self, application, outcome_type):
        event = OutcomeEvent(
            id=OutcomeEventId(new_id()),
            application_id=application.id,
            type=outcome_type,
            source=OutcomeSource.AUTO,
        )
        self._storage.outcomes.add(event)
        event_bus.emit(
            OutcomeRecorded(
                application_id=application.id,
                outcome_type=outcome_type,
                source="auto",
                reason=f"post-submission: {outcome_type}",
            )
        )
        return event
