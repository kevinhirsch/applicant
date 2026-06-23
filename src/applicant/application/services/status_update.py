"""StatusUpdateService — the proactive periodic agent status update (FR-AGENT-7 / FR-OBS-2).

This is the PUSH sibling of the chatbot's self-report (``ChatService._status_context``)
and the activity panel: once per UTC day the autonomous agent pushes a short, plain-
language, FIRST-PERSON summary of what it has been doing and plans to do next, through
the EXISTING notification system (in-app inbox + the user's opt-in channel fan-out) —
NOT a parallel channel (binding principle #1).

The message is assembled fresh from the SAME read-only sources the chat self-report uses
(scheduler heartbeat, the per-campaign run status + the FR-AGENT-7 next-action sentence,
recent application history/outcomes, the pending-actions count). Every source is wrapped
defensively: an absent or erroring source contributes NOTHING and is never replaced with
an invented value (no fabrication, FR-AGENT-5). When nothing meaningful can be said, the
service emits nothing at all.

Scheduling/idempotency live in the scheduler (mirroring the daily digest + curation
nudge): this service only assembles + emits one update on demand.
"""

from __future__ import annotations

from datetime import datetime

from applicant.observability.logging import get_logger

log = get_logger(__name__)


class StatusUpdateService:
    """Assembles + pushes the once-daily plain-language agent status update."""

    def __init__(
        self,
        *,
        notification_service=None,
        agent_run_service=None,
        admin_query=None,
        pending_actions=None,
        scheduler=None,
    ) -> None:
        # The EXISTING notification path (in-app inbox + opt-in fan-out). Reused, not
        # rebuilt (principle #1). When None the service is a no-op (degrades gracefully).
        self._notifications = notification_service
        # Read-only state sources, mirroring the chat self-report. All optional: a
        # missing source simply contributes no line (FR-AGENT-5 — no fabrication).
        self._agent_runs = agent_run_service
        self._admin_query = admin_query
        self._pending_actions = pending_actions
        self._scheduler = scheduler

    def dedup_key(self, campaign_id, day) -> str:
        """Stable per-(campaign, UTC day) idempotency key (FR-NOTIF-3).

        The scheduler already guards the once-per-day cadence; this key makes a
        re-driven same-day emit no-op at the notifier too (defense in depth).
        """
        return f"status_update:{campaign_id}:{day.isoformat()}"

    def emit(self, campaign_id, now: datetime) -> str | None:
        """Assemble + push one status update for ``campaign_id``.

        Returns the notification handle when something was pushed, or ``None`` when
        there was nothing meaningful to report (then nothing is emitted) or no notifier
        is wired. Bounded + truthful — see :meth:`build_message`.
        """
        if self._notifications is None:
            return None
        body = self.build_message(campaign_id, now)
        if not body:
            return None
        notify = getattr(self._notifications, "notify_status_update", None)
        if notify is None:  # pragma: no cover - defensive (older notifier)
            return None
        return notify(
            campaign_id=str(campaign_id),
            body=body,
            day=now.date(),
            deep_link="/activity",
        )

    # --- message assembly (truthful, FR-AGENT-5) --------------------------
    def build_message(self, campaign_id, now: datetime) -> str | None:
        """A SHORT first-person update assembled from real read-only state.

        Three beats ("Since yesterday I … / Right now I'm … / Next I'll …"), each line
        sourced from real state. A source that is absent/empty/erroring contributes
        nothing and is NEVER replaced with an invented value. Returns ``None`` when no
        source yields anything (so the scheduler emits nothing).
        """
        past = self._past_lines(campaign_id)
        present = self._present_lines(campaign_id, now)
        future = self._future_lines(campaign_id)

        if not (past or present or future):
            return None

        parts: list[str] = []
        if past:
            parts.append("Since yesterday I " + _join(past) + ".")
        if present:
            parts.append("Right now " + _join(present) + ".")
        if future:
            parts.append("Next I'll " + _join(future) + ".")
        return " ".join(parts)

    # --- past: recent applications + their applied count ------------------
    def _past_lines(self, campaign_id) -> list[str]:
        lines: list[str] = []
        # Today's applied count (the truthful "how much have I done" number).
        run_status = self._safe_run_status(campaign_id)
        if run_status is not None:
            applied = run_status.get("applied_today")
            if isinstance(applied, int) and applied > 0:
                budget = run_status.get("daily_budget")
                bit = f"started {applied} application{_s(applied)}"
                if isinstance(budget, int) and budget:
                    bit += f" toward today's budget of {budget}"
                lines.append(bit)
        # Recent roles (titles only — no invented status).
        if self._admin_query is not None:
            history = self._safe_history(campaign_id)
            titles = []
            for row in history:
                title = (row.get("job_title") or row.get("role_name") or "").strip()
                if title:
                    titles.append(title)
            titles = titles[:3]
            if titles:
                lines.append("worked on " + _join_items(titles))
        return lines

    # --- present: am I working, and is my work paused ---------------------
    def _present_lines(self, campaign_id, now: datetime) -> list[str]:
        lines: list[str] = []
        run_status = self._safe_run_status(campaign_id)
        if run_status is not None and run_status.get("paused"):
            lines.append("my automated work is paused")
        if self._scheduler is not None:
            sched = self._safe_scheduler_state()
            if sched is not None and sched.get("running"):
                lines.append("I'm running a work cycle")
        return lines

    # --- future: next-action intent + what's pending ----------------------
    def _future_lines(self, campaign_id) -> list[str]:
        lines: list[str] = []
        run_status = self._safe_run_status(campaign_id)
        if run_status is not None:
            intent = (run_status.get("latest_intent") or "").strip()
            if intent:
                # The FR-AGENT-7 single-sentence intent. Lower-case the first letter so
                # it reads naturally after "Next I'll" without claiming more than stated.
                lines.append(_decapitalize(intent.rstrip(".")))
        if self._pending_actions is not None:
            count = self._safe_pending_count(campaign_id)
            if count > 0:
                lines.append(
                    f"keep {count} item{_s(count)} waiting for your review in your portal"
                )
        return lines

    # --- defensive source wrappers (FR-AGENT-5) ---------------------------
    def _safe_run_status(self, campaign_id):
        if self._agent_runs is None:
            return None
        try:
            return self._agent_runs.status(campaign_id)
        except Exception:  # pragma: no cover - defensive
            return None

    def _safe_history(self, campaign_id) -> list:
        try:
            return list(self._admin_query.application_history(campaign_id, limit=5) or [])
        except TypeError:  # adapters without the ``limit`` kwarg
            try:
                return list(self._admin_query.application_history(campaign_id) or [])[:5]
            except Exception:  # pragma: no cover - defensive
                return []
        except Exception:  # pragma: no cover - defensive
            return []

    def _safe_scheduler_state(self):
        try:
            return self._scheduler.state()
        except Exception:  # pragma: no cover - defensive
            return None

    def _safe_pending_count(self, campaign_id) -> int:
        try:
            return len(list(self._pending_actions.list_pending(campaign_id) or []))
        except Exception:  # pragma: no cover - defensive
            return 0


# --- small text helpers (pure) -------------------------------------------
def _s(n: int) -> str:
    return "" if n == 1 else "s"


def _decapitalize(text: str) -> str:
    return text[:1].lower() + text[1:] if text else text


def _join(parts: list[str]) -> str:
    """Join clauses with commas + a trailing 'and' (plain language)."""
    parts = [p for p in parts if p]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def _join_items(items: list[str]) -> str:
    return _join(list(items))
