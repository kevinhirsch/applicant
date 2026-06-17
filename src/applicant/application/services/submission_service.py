"""SubmissionService — detection, logging, screenshots, conversion capture.

Closes the end of the §7 lifecycle (FR-LOG-1/2/4, FR-LEARN-2):

* **Auto-detect** the final submission in the controlled session via the browser
  adapter's confirmation-page heuristics (FR-LOG-4); where it cannot be auto-detected
  (e.g. the emergency data-handoff) the one-tap **mark-submitted** path applies.
* Each detected/marked submission creates an :class:`OutcomeEvent` so conversion
  learning sees *real* conversions, not just approvals (FR-LEARN-2).
* On completion, **log every detail** to the ``applications`` row — attributes/values
  used, the resume variant used (placeholder until Phase 3), role/title/work-mode,
  and the root application URL (FR-LOG-1).
* **Archive per-page screenshots** to ``application_screenshots`` via the storage port
  (FR-LOG-2); the screenshot bytes stay behind the browser/storage port as a
  path/blob ref seam.

Terminal state follows the §7 transitions: SUBMITTED_BY_USER (user submitted) or
FINISHED_BY_ENGINE (friction-free, user-authorized).
"""

from __future__ import annotations

from applicant.core.entities.application import Application
from applicant.core.entities.application_screenshot import ApplicationScreenshot
from applicant.core.entities.outcome_event import OutcomeEvent, OutcomeSource
from applicant.core.ids import (
    ApplicationId,
    OutcomeEventId,
    ScreenshotId,
    new_id,
)
from applicant.core.rules.review_gate import ReviewableMaterial, ensure_submittable
from applicant.core.state_machine import ApplicationState
from applicant.observability.logging import get_logger

log = get_logger(__name__)


class SubmissionService:
    def __init__(self, storage, browser=None, *, learning=None, advanced_learning=None) -> None:
        self._storage = storage
        self._browser = browser
        # Optional LearningService so a real submission records the SUBMISSIONS leg of
        # the source-yield funnel (FR-DISC-5/FR-LEARN-6) — the conversion target.
        self._learning = learning
        # Optional AdvancedLearningService so EVERY submit path (remote terminal,
        # outcomes auto-detect / mark-submitted, the durable pipeline) folds the
        # converting-role signature once a real conversion lands (FR-LEARN-2). Moving
        # this here means the remote path no longer silently skips conversion learning.
        self._advanced_learning = advanced_learning

    # --- detection (FR-LOG-4) ---------------------------------------------
    def detect_submission(self, application_id: ApplicationId) -> bool:
        """Auto-detect a final submission via the confirmation-page heuristics.

        Returns True if the controlled session is now on a post-submission
        confirmation page. Conservative: only fires on a clear confirmation signal.
        """
        if self._browser is None:
            return False
        detector = getattr(self._browser, "is_confirmation_page", None)
        if detector is None:
            return False
        try:
            return bool(detector(application_id))
        except Exception:  # pragma: no cover - defensive: a driver error never converts
            return False

    # --- review gate before submission (FR-RESUME-8) ----------------------
    def ensure_submittable(self, application_id: ApplicationId) -> None:
        """Raise ``ReviewRequired`` if any generated material is unapproved.

        FR-RESUME-8: review-before-submission is enforced HERE, in the service that
        every submit path funnels through (``record_submission``/``mark_submitted``),
        so the gate cannot be bypassed per-router by a present or future caller.
        """
        docs = self._storage.documents.list_for_application(application_id)
        materials = [
            ReviewableMaterial(identifier=str(d.id), is_generated=True, approved=d.approved)
            for d in docs
        ]
        ensure_submittable(materials)

    # --- terminal completion (FR-LOG-1/2/4, FR-LEARN-2) -------------------
    def record_submission(
        self,
        application: Application,
        *,
        source: OutcomeSource,
        attributes_used: dict | None = None,
        screenshots: list[str] | None = None,
        screenshot_pages: list[str] | None = None,
        resume_variant_id: str | None = None,
    ) -> OutcomeEvent:
        """Log the completed application + archive screenshots + emit an OutcomeEvent.

        ``source`` distinguishes auto-detected from one-tap mark-submitted (FR-LOG-4).
        The terminal state is derived from the source: AUTO -> engine finished,
        MANUAL -> user submitted (§7).

        FR-RESUME-8: before ANYTHING is recorded, the review gate is enforced — all
        generated material for this application must be approved, else ``ReviewRequired``.

        IDEM-3: idempotent — if a submitted ``OutcomeEvent`` already exists for this
        application (e.g. the submit step re-ran after a dropped checkpoint, CONC-1),
        return the existing event WITHOUT recording a second one (no duplicate
        OutcomeEvent / double-counted submissions funnel).
        """
        existing_event = self._existing_submission(application.id)
        if existing_event is not None:
            log.info("submission_already_recorded", application_id=str(application.id))
            return existing_event
        self.ensure_submittable(application.id)
        terminal = (
            ApplicationState.FINISHED_BY_ENGINE
            if source is OutcomeSource.AUTO
            else ApplicationState.SUBMITTED_BY_USER
        )
        logged = self._log_application(
            application,
            terminal=terminal,
            attributes_used=attributes_used,
            resume_variant_id=resume_variant_id,
        )
        self._archive_screenshots(application.id, screenshots or [], screenshot_pages or [])
        event = OutcomeEvent(
            id=OutcomeEventId(new_id()),
            application_id=application.id,
            type="submitted",
            source=source,
        )
        self._storage.outcomes.add(event)
        self._storage.commit()
        self._record_submission_yield(application)
        # FR-LEARN-2: a recorded submission (with approval) is a REAL conversion —
        # fold the converting-role signature here so EVERY submit path closes the
        # learning loop, not only the outcomes router (#2). Best-effort.
        self._close_conversion_loop(logged)
        log.info(
            "submission_recorded",
            application_id=str(application.id),
            source=source.value,
            terminal=terminal.value,
            screenshots=len(screenshots or []),
        )
        # keep the logged app available to callers
        self._last_logged = logged
        return event

    def mark_submitted(
        self, application: Application, *, attributes_used: dict | None = None
    ) -> OutcomeEvent:
        """One-tap mark-submitted fallback when auto-detection cannot confirm (FR-LOG-4)."""
        return self.record_submission(
            application, source=OutcomeSource.MANUAL, attributes_used=attributes_used
        )

    # --- retrieval (FR-LOG-3 surface, minimal) ----------------------------
    def get_log(self, application_id: ApplicationId) -> dict:
        """Return the logged application detail + screenshots + outcomes (FR-LOG-3)."""
        app = self._storage.applications.get(application_id)
        shots = self._storage.screenshots.list_for_application(application_id)
        outcomes = self._storage.outcomes.list_for_application(application_id)
        return {
            "application_id": str(application_id),
            "status": app.status.value if app else None,
            "role_name": app.role_name if app else None,
            "job_title": app.job_title if app else None,
            "work_mode": app.work_mode if app else None,
            "root_url": app.root_url if app else None,
            "resume_variant_id": app.resume_variant_id if app else None,
            "attributes_used": dict(app.attributes_used) if app else {},
            "screenshots": [
                {"id": str(s.id), "page_ref": s.page_ref, "page_url": s.page_url}
                for s in shots
            ],
            "outcomes": [{"type": o.type, "source": o.source.value} for o in outcomes],
        }

    def _existing_submission(self, application_id: ApplicationId) -> OutcomeEvent | None:
        """Return a prior ``submitted`` OutcomeEvent for this app, if any (IDEM-3)."""
        try:
            outcomes = self._storage.outcomes.list_for_application(application_id)
        except Exception:  # pragma: no cover - defensive
            return None
        for ev in outcomes:
            if ev.type == "submitted":
                return ev
        return None

    def _close_conversion_loop(self, application: Application) -> None:
        """Fold the now-converted application into per-campaign learning (FR-LEARN-2).

        Conversion = approval (the terminal state just logged) PLUS submission (the
        OutcomeEvent just recorded). Reads outcomes from storage, folds the rich
        converting-role signature, persists. Defensive: learning never breaks a
        recorded submission. Moved here from the outcomes router so the remote
        terminal path (and any future submit path) also closes the loop (#2).
        """
        if self._advanced_learning is None or not application.campaign_id:
            return
        posting = None
        if application.posting_id:
            try:
                posting = self._storage.postings.get(application.posting_id)
            except Exception:  # pragma: no cover - defensive
                posting = None
        try:
            self._advanced_learning.record_and_persist_conversion(
                application.campaign_id, application, posting=posting
            )
        except Exception:  # pragma: no cover - learning must never break a submission
            pass

    def _record_submission_yield(self, application: Application) -> None:
        """Record the SUBMISSIONS leg of the source-yield funnel (FR-DISC-5/FR-LEARN-6)."""
        if self._learning is None or application.posting_id is None:
            return
        posting = self._storage.postings.get(application.posting_id)
        if posting is None or not posting.source_key:
            return
        try:
            self._learning.record_source_event(
                posting.campaign_id, posting.source_key, "submissions"
            )
        except Exception:  # pragma: no cover - learning must never break a submission
            pass

    # --- internals --------------------------------------------------------
    def _log_application(
        self,
        application: Application,
        *,
        terminal: ApplicationState,
        attributes_used: dict | None,
        resume_variant_id: str | None,
    ) -> Application:
        import dataclasses

        app = application.with_status(terminal)
        if attributes_used is not None:
            app = dataclasses.replace(app, attributes_used=dict(attributes_used))
        if resume_variant_id is not None:
            from applicant.core.ids import ResumeVariantId

            app = dataclasses.replace(app, resume_variant_id=ResumeVariantId(resume_variant_id))
        existing = self._storage.applications.get(app.id)
        if existing is None:
            self._storage.applications.add(app)
        else:
            self._storage.applications.update(app)
        return app

    def _archive_screenshots(
        self, application_id: ApplicationId, refs: list[str], pages: list[str]
    ) -> None:
        for i, ref in enumerate(refs):
            page_url = pages[i] if i < len(pages) else ""
            self._storage.screenshots.add(
                ApplicationScreenshot(
                    id=ScreenshotId(new_id()),
                    application_id=application_id,
                    page_ref=ref,
                    page_url=page_url,
                )
            )
