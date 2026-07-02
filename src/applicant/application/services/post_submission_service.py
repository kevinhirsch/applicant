"""PostSubmissionService -- post-submission lifecycle tracking (G16/#190)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from applicant.core.entities.follow_up import FollowUp, FollowUpTemplate
from applicant.core.entities.ghosting_signal import GhostingSignal
from applicant.core.entities.outcome_event import OutcomeEvent, OutcomeSource, is_recognized_outcome
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

#: The §7 states shown on the front-door tracker board (#4 of the design audit
#: Top-25): the terminal-submit states before the tracker/scheduler has pivoted
#: them to POST_SUBMISSION, plus the full post-submission lifecycle itself. An
#: application still earlier in the pipeline (DISCOVERED..AWAITING_FINAL_APPROVAL)
#: has nothing to track yet and is intentionally excluded.
TRACKER_STATES: frozenset[ApplicationState] = frozenset(
    {
        ApplicationState.SUBMITTED_BY_USER,
        ApplicationState.FINISHED_BY_ENGINE,
        ApplicationState.POST_SUBMISSION,
        ApplicationState.AWAITING_RESPONSE,
        ApplicationState.FOLLOWING_UP,
        ApplicationState.REJECTED,
        ApplicationState.GHOSTED,
        ApplicationState.ARCHIVED,
    }
)

#: Manually-recordable outcomes that carry a positive "signal" badge on the
#: tracker board. Both are recognized ``OutcomeEvent.type`` values (see
#: ``core/entities/outcome_event.py``) but have no dedicated §7 state of their
#: own -- they are layered onto whatever waiting state the application is
#: actually in (see ``record_manual_outcome``).
POSITIVE_SIGNAL_TYPES: frozenset[str] = frozenset({"interview_invited", "offer"})

#: Manual outcome types that DO drive a §7 status transition, mapped to the
#: target state. Kept minimal and explicit -- a type absent from this mapping
#: (e.g. the positive signals above, or "submitted"/"converted") never touches
#: ``Application.status``, only the outcome trail.
_MANUAL_OUTCOME_STATUS: dict[str, ApplicationState] = {
    "rejected": ApplicationState.REJECTED,
    "ghosted": ApplicationState.GHOSTED,
}


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

    def _record_outcome_event(self, application, outcome_type, *, source=OutcomeSource.AUTO):
        event = OutcomeEvent(
            id=OutcomeEventId(new_id()),
            application_id=application.id,
            type=outcome_type,
            source=source,
        )
        self._storage.outcomes.add(event)
        event_bus.emit(
            OutcomeRecorded(
                application_id=application.id,
                outcome_type=outcome_type,
                source=source.value,
                reason=f"post-submission: {outcome_type}",
            )
        )
        return event

    # --- tracker board (design-audit Top-25 #4) -----------------------------

    def list_tracker_rows(self, campaign_id):
        """One row per in-flight/closed application, newest first (the tracker board).

        Reads straight off ``Application.status`` for the row's bucket (applied /
        awaiting response / following up / rejected / ghosted / archived) and layers
        on any recorded positive signal (``interview_invited`` / ``offer``) from the
        outcome trail, since those have no dedicated §7 state of their own. Pure
        read -- no state is mutated. Applications earlier than the terminal-submit
        states (still being matched/prefilled/reviewed) are not tracker rows.
        """
        rows = []
        for app in self._storage.applications.list_for_campaign(campaign_id):
            if app.status not in TRACKER_STATES:
                continue
            events = list(self._storage.outcomes.list_for_application(app.id))
            signals = sorted({e.type for e in events if e.type in POSITIVE_SIGNAL_TYPES})
            snapshot = self._storage.submission_snapshots.get_for_application(app.id)
            submitted_at = snapshot.captured_at if snapshot is not None else None
            rows.append(
                {
                    "application_id": str(app.id),
                    "status": app.status.value,
                    "role_name": app.role_name,
                    "job_title": app.job_title,
                    "signals": signals,
                    "submitted_at": submitted_at.isoformat() if submitted_at else None,
                    "created_at": app.created_at.isoformat() if app.created_at else None,
                }
            )
        rows.sort(key=lambda r: r["submitted_at"] or r["created_at"] or "", reverse=True)
        return rows

    def record_manual_outcome(self, application_id, outcome_type):
        """Owner-triggered "record what happened" write for the tracker board.

        The manual sibling of the automated detection paths (``detect_outcome`` /
        ``process_rejection_signal`` / ``check_ghosting``, which only ever record
        ``OutcomeSource.AUTO``). Only a recognized ``OUTCOME_TYPES`` value is
        accepted. When the type maps to a §7 status (``rejected`` -> REJECTED,
        ``ghosted`` -> GHOSTED via ``_MANUAL_OUTCOME_STATUS``), the application
        transitions too -- best-effort: an illegal transition from the
        application's CURRENT status (e.g. it was already ARCHIVED) is swallowed
        rather than raised, so a stale tap can never corrupt the state machine; the
        outcome event is still recorded either way. Positive signals
        (``interview_invited`` / ``offer``) never touch status -- see
        ``POSITIVE_SIGNAL_TYPES``. Returns ``None`` when the application does not
        exist (caller maps that to 404); raises ``ValueError`` for an unrecognized
        ``outcome_type`` so the router can 422 instead of silently no-op'ing.
        """
        if not is_recognized_outcome(outcome_type):
            raise ValueError(f"Unrecognized outcome type: {outcome_type!r}")
        app = self._storage.applications.get(application_id)
        if app is None:
            return None
        target_status = _MANUAL_OUTCOME_STATUS.get(outcome_type)
        if target_status is not None and app.status != target_status:
            try:
                app = app.with_status(target_status)
                self._storage.applications.update(app)
            except Exception:
                pass
        event = self._record_outcome_event(app, outcome_type, source=OutcomeSource.MANUAL)
        self._storage.commit()
        return event
