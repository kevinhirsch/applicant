"""PipelineSummaryService — cheap funnel + daily-progress read model (APP-LP-1).

Backs the landing-page "Pipeline Funnel" and "Daily Progress" gadgets
(``docs/stories/landing-page-overhaul.md``). Every number here comes from a
handful of indexed ``COUNT``/range queries against existing tables — it never
re-scores a posting, never rebuilds the digest, and never hydrates every
application row. Kept under the story's <1s budget by construction: the
heaviest single call is a range scan on ``action_events`` bounded by
``STREAK_LOOKBACK_DAYS``, which is small for a single-user job search.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

from applicant.core.ids import CampaignId
from applicant.core.state_machine import ApplicationState as S

#: Landing-page funnel semantics (product decision, APP-LP-1 overseer review):
#: a posting counts as "Drafted" once its application has left the bare
#: discovery/scoring stage and entered the active decision funnel — i.e. from
#: ``DIGESTED`` onward — NOT only once ``MATERIAL_PREP`` literally starts.
#: ``DIGESTED`` is the state ``DigestService`` promotes an approved-for-review
#: posting to (see ``digest_service.py``'s ``_application_for``), so it is the
#: earliest point a "Top New Matches" row becomes a real, trackable
#: application; that is honestly closer to what a job-seeker means by "in my
#: drafted pile" than gating on the engine's internal MATERIAL_PREP step.
#: Excluded: ``DISCOVERED``/``SCORED`` (still bare postings, no application
#: yet) and the terminal non-outcomes ``DECLINED``/``FAILED`` (never drafted).
_PRE_DRAFT_STATES = frozenset({S.DISCOVERED.value, S.SCORED.value})
_NEVER_DRAFTED_STATES = frozenset({S.DECLINED.value, S.FAILED.value})
DRAFTED_OR_LATER: tuple[S, ...] = tuple(
    s for s in S if s.value not in _PRE_DRAFT_STATES and s.value not in _NEVER_DRAFTED_STATES
)

#: Reached submission or later.
SUBMITTED_OR_LATER: tuple[S, ...] = (
    S.SUBMITTED_BY_USER,
    S.FINISHED_BY_ENGINE,
    S.POST_SUBMISSION,
    S.AWAITING_RESPONSE,
    S.REJECTED,
    S.GHOSTED,
    S.FOLLOWING_UP,
    S.ARCHIVED,
)

#: Outcome types that count as "got an interview" for the funnel's top stage.
INTERVIEW_OUTCOME_TYPES: tuple[str, ...] = ("interview_invited",)

#: How far back to look when computing the "submitted at least one today"
#: streak. Bounded so the ``action_events`` range scan stays small and fast.
STREAK_LOOKBACK_DAYS = 60

#: ``ActionEvent.action`` value the audit log writes for every application
#: state transition (see ``AuditLogService._ACTION_MAP``); its ``context``
#: carries ``{"from_state": ..., "to_state": ...}``.
_STATE_CHANGED_ACTION = "state_changed"

_SUBMITTED_TO_STATES = frozenset({S.SUBMITTED_BY_USER.value, S.FINISHED_BY_ENGINE.value})


class PipelineSummaryService:
    """Read-only aggregate over postings/applications/outcomes/action-events."""

    def __init__(self, storage) -> None:
        self._storage = storage

    def get_summary(self, campaign_id: CampaignId, now: datetime | None = None) -> dict:
        now = now or datetime.now(UTC)
        today: date = now.date()
        start_of_today = datetime.combine(today, time.min, tzinfo=UTC)

        funnel = {
            "discovered": int(self._storage.postings.count_for_campaign(campaign_id)),
            "scored": int(self._storage.postings.count_scored_for_campaign(campaign_id)),
            "drafted": int(
                self._storage.applications.count_by_status(campaign_id, DRAFTED_OR_LATER)
            ),
            "submitted": int(
                self._storage.applications.count_by_status(campaign_id, SUBMITTED_OR_LATER)
            ),
            "interview": int(
                self._storage.outcomes.count_distinct_applications_for_campaign(
                    campaign_id, INTERVIEW_OUTCOME_TYPES
                )
            ),
        }

        since = start_of_today - timedelta(days=STREAK_LOOKBACK_DAYS)
        recent = self._storage.action_events.list_since(
            campaign_id, since, action=_STATE_CHANGED_ACTION
        )

        today_drafted = 0
        today_submitted = 0
        submitted_days: set[date] = set()
        for event in recent:
            to_state = (event.context or {}).get("to_state")
            day = event.occurred_at.date()
            if to_state == S.DIGESTED.value and day == today:
                today_drafted += 1
            if to_state in _SUBMITTED_TO_STATES:
                submitted_days.add(day)
                if day == today:
                    today_submitted += 1

        streak_days = 0
        cursor = today
        while cursor in submitted_days:
            streak_days += 1
            cursor -= timedelta(days=1)

        return {
            "campaign_id": str(campaign_id),
            "funnel": funnel,
            "today": {"drafted": today_drafted, "submitted": today_submitted},
            "streak_days": streak_days,
        }
