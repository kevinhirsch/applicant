"""Run-history provider for the curation nudge (FR-MIND-7/-13).

The scheduled curation loop (``CurationService.run_curation_tick``) reviews recent
engine runs and proposes memory updates + skills — but it only learns if it is fed
**real run history**. This module is the small, cheap reader that maps the engine's
own durable work (recent applications + their outcomes) into the deterministic
:class:`RunSummary` records the curator consumes.

It mirrors how :mod:`learning_advanced` reads ``applications``/``outcomes`` from
``storage``: it walks each active campaign's recent applications, reads each
application's outcome events, and emits one ``RunSummary`` per application. The
output is **bounded** (``max_summaries``) so the nudge stays cheap and never floods
the loop (FR-MIND-13), and **deterministic** so re-runs are idempotent (the curator
also content-hash-dedupes by ``run_id``).

No LLM, no network — pure storage reads, so the hermetic lane runs it unchanged.
"""

from __future__ import annotations

from datetime import datetime

from applicant.core.entities.application import Application
from applicant.core.state_machine import ApplicationState
from applicant.observability.logging import get_logger

log = get_logger(__name__)

#: Default cap on summaries handed to one curation tick (FR-MIND-13 — keep it cheap).
DEFAULT_MAX_SUMMARIES = 25

#: Outcome event types that mark a run as actually submitted/converted (FR-LOG-4),
#: mirroring ``learning_advanced._SUBMISSION_TYPES``.
_SUBMISSION_TYPES = frozenset({"submitted", "converted"})

#: Application states that indicate the run reached a meaningful, reviewable outcome
#: (cleared discovery/scoring and got somewhere). Trivial just-discovered/just-scored
#: rows carry no lesson, so they are skipped to keep the nudge cheap.
_REVIEWABLE_STATES = frozenset(
    s
    for s in ApplicationState
    if s not in (ApplicationState.DISCOVERED, ApplicationState.SCORED)
)


class RunHistoryProvider:
    """Maps recent stored applications + outcomes -> ``RunSummary`` (FR-MIND-7).

    Callable as ``provider(storage, now)`` so it drops straight into the scheduler's
    ``run_summaries_provider`` slot. ``storage`` is whatever per-tick storage the
    scheduler hands in (so the read runs against the isolated per-tick session).
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
            log.warning("run_history_campaigns_failed", error=str(exc))
            return []

        for campaign in campaigns:
            if not getattr(campaign, "active", True):
                continue
            try:
                apps = list(storage.applications.list_for_campaign(campaign.id))
            except Exception as exc:  # pragma: no cover - defensive
                log.warning("run_history_apps_failed", error=str(exc))
                continue
            for app in apps:
                if app.status not in _REVIEWABLE_STATES:
                    continue
                summary = self._to_summary(storage, app)
                if summary is not None:
                    summaries.append(summary)
                    if len(summaries) >= self._max:
                        return summaries
        return summaries

    def _to_summary(self, storage, app: Application):
        from applicant.application.services.curation_service import RunSummary

        try:
            outcomes = storage.outcomes.list_for_application(app.id)
        except Exception:  # pragma: no cover - defensive
            outcomes = []
        submitted = any(getattr(e, "type", "") in _SUBMISSION_TYPES for e in outcomes)
        title = app.job_title or app.role_name or "an application"
        # A stable topic so re-encounters of the same site/role map to the same skill.
        # The ATS host (from root_url) is the most reusable key when present.
        topic = _host(app.root_url) or _slug(title)
        verb = "Submitted" if submitted else f"Worked {app.status.value}"
        text = f"{verb} {title}".strip()
        if app.root_url:
            text = f"{text} ({app.root_url})"
        return RunSummary(
            run_id=str(app.id),
            campaign_id=str(app.campaign_id),
            text=text,
            # A real, reviewed application is a non-trivial run worth a skill when it
            # was actually submitted (the strongest "this worked" signal, FR-MIND-2).
            tool_calls=5 if submitted else 0,
            succeeded=submitted or app.status in _REVIEWABLE_STATES,
            topic=topic,
        )


def _host(url: str | None) -> str:
    if not url:
        return ""
    try:
        from urllib.parse import urlparse

        host = urlparse(url).hostname or ""
    except Exception:  # pragma: no cover - defensive
        return ""
    return host.lower().removeprefix("www.")


def _slug(text: str) -> str:
    out = []
    for ch in (text or "").lower():
        if ch.isalnum():
            out.append(ch)
        elif out and out[-1] != "-":
            out.append("-")
    return "".join(out).strip("-")[:60]
