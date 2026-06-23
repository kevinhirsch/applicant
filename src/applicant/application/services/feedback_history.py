"""Feedback-history provider for the curation nudge (FR-MIND-1/-7/-13, FR-LEARN-3).

The scheduled curation loop (``CurationService.run_curation_tick``) reviews recent
*runs* and proposes memory/skills — but "learn from **every** input" (FR-LEARN-3)
means the user's own stated feedback should feed the curated-memory substrate too,
as their **preferences/corrections** (FR-MIND-1's user-memory half), not as the
agent's environment lessons.

This module is the small, cheap reader that maps the user's recent feedback into the
deterministic :class:`RunSummary` records the curator consumes, each tagged
``is_preference=True`` so the curator proposes a curated **user** memory line (never a
skill). Two feedback sources are covered (FR-LEARN-3):

* **digest decline-with-feedback** (FR-DIG-5) — a declined digest row whose
  ``Decision.feedback_text`` is the user's stated reason for passing;
* **résumé/answer revision feedback** (FR-RESUME-8) — each add/subtract/free-text
  ``RevisionTurn.instruction`` the user gave while redlining a generated material.

It mirrors :mod:`run_history`: it walks each active campaign's recent applications,
reads each application's stored decisions + its materials' revision sessions, and
emits one ``RunSummary`` per piece of feedback. The output is **bounded**
(``max_summaries``) so the nudge stays cheap and never floods the loop (FR-MIND-13),
and **deterministic** so re-runs are idempotent (the curator content-hash-dedupes by
``run_id``).

No LLM, no network — pure storage reads, so the hermetic lane runs it unchanged.
"""

from __future__ import annotations

from datetime import datetime

from applicant.observability.logging import get_logger

log = get_logger(__name__)

#: Default cap on feedback summaries handed to one curation tick (FR-MIND-13 — cheap).
DEFAULT_MAX_SUMMARIES = 25


class FeedbackSummaryProvider:
    """Maps recent user feedback -> preference ``RunSummary`` (FR-LEARN-3, FR-MIND-1).

    Callable as ``provider(storage, now)`` so it drops straight into the scheduler's
    ``run_summaries_provider`` slot (composed alongside the run-history provider).
    ``storage`` is whatever per-tick storage the scheduler hands in, so the read runs
    against the isolated per-tick session.
    """

    def __init__(self, *, max_summaries: int = DEFAULT_MAX_SUMMARIES) -> None:
        self._max = max(1, int(max_summaries))

    def __call__(self, storage, now: datetime | None = None) -> list:
        # Imported here so the layering is clean and there is no import cycle with
        # curation_service (which imports nothing from here).
        from applicant.application.services.curation_service import RunSummary

        summaries: list[RunSummary] = []
        try:
            campaigns = list(storage.campaigns.list())
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("feedback_history_campaigns_failed", error=str(exc))
            return []

        for campaign in campaigns:
            if not getattr(campaign, "active", True):
                continue
            try:
                apps = list(storage.applications.list_for_campaign(campaign.id))
            except Exception as exc:  # pragma: no cover - defensive
                log.warning("feedback_history_apps_failed", error=str(exc))
                continue
            for app in apps:
                for summary in self._feedback_for_app(storage, campaign, app):
                    summaries.append(summary)
                    if len(summaries) >= self._max:
                        return summaries
        return summaries

    def _feedback_for_app(self, storage, campaign, app):
        """Yield one preference ``RunSummary`` per stored feedback item for ``app``."""
        from applicant.application.services.curation_service import RunSummary

        campaign_id = str(getattr(campaign, "id", "") or "")

        # 1) digest decline-with-feedback (FR-DIG-5): the user's stated decline reason.
        try:
            decisions = storage.decisions.list_for_application(app.id)
        except Exception:  # pragma: no cover - defensive
            decisions = []
        for d in decisions:
            text = (getattr(d, "feedback_text", "") or "").strip()
            if not text:
                continue  # only declines that carry a stated reason are a lesson
            yield RunSummary(
                run_id=f"feedback-decline-{getattr(d, 'id', app.id)}",
                campaign_id=campaign_id or None,
                text=f"You declined a match and said: {text}",
                # Not a workflow — a stated preference. tool_calls=0 keeps it
                # skill-ineligible even before the curator's is_preference guard.
                tool_calls=0,
                succeeded=True,
                topic=_topic_for_app(app, "declines"),
                is_preference=True,
            )

        # 2) résumé/answer revision feedback (FR-RESUME-8): each redline instruction.
        try:
            documents = storage.documents.list_for_application(app.id)
        except Exception:  # pragma: no cover - defensive
            documents = []
        for doc in documents:
            try:
                session = storage.revisions.get_for_material(doc.id)
            except Exception:  # pragma: no cover - defensive
                session = None
            if session is None:
                continue
            for i, turn in enumerate(getattr(session, "turns", ()) or ()):
                instruction = (getattr(turn, "instruction", "") or "").strip()
                if not instruction:
                    continue
                kind = getattr(turn, "kind", "") or "edit"
                yield RunSummary(
                    run_id=f"feedback-revision-{getattr(session, 'id', doc.id)}-{i}",
                    campaign_id=campaign_id or None,
                    text=f"You revised generated material ({kind}): {instruction}",
                    tool_calls=0,
                    succeeded=True,
                    topic=_topic_for_doc(doc),
                    is_preference=True,
                )


def _topic_for_app(app, suffix: str) -> str:
    """A stable preference-area topic key for a declined application."""
    base = getattr(app, "job_title", None) or getattr(app, "role_name", None) or "matches"
    return f"preference-{_slug(base)}-{suffix}"


def _topic_for_doc(doc) -> str:
    """A stable preference-area topic key for a revised material."""
    dtype = getattr(getattr(doc, "type", None), "value", None) or "material"
    return f"preference-{_slug(str(dtype))}"


def _slug(text: str) -> str:
    out = []
    for ch in (text or "").lower():
        if ch.isalnum():
            out.append(ch)
        elif out and out[-1] != "-":
            out.append("-")
    return "".join(out).strip("-")[:60] or "general"
