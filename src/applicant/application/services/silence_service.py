"""SilenceService — ghosting / silence SLA tracking (#192, FR-LOG-4).

Nothing previously tracked how long a submitted application had gone without a
response, so an application could sit silent forever with no signal. This service
tracks the elapsed time since submission and flags an application as *likely
ghosted* once that silence crosses a no-response SLA threshold — feeding a
``ghosted`` outcome (FR-LEARN-2) and surfacing the application for a follow-up or
close-out decision.

Pure and hermetic: the elapsed-time and SLA helpers are deterministic functions
over timestamps / day counts, testable in CI without a clock or DB.
"""

from __future__ import annotations

from datetime import UTC, datetime

#: Days of total silence after which an application is considered likely ghosted.
#: ~30 days is the common "no response means no" horizon for job applications; a
#: conservative default so a still-in-review application is not prematurely closed.
DEFAULT_GHOST_SLA_DAYS = 30


class SilenceService:
    """Track silence since submission and flag likely-ghosted applications (#192)."""

    def __init__(self, *, ghost_sla_days: int = DEFAULT_GHOST_SLA_DAYS) -> None:
        self._sla_days = int(ghost_sla_days)

    @property
    def sla_days(self) -> int:
        """The no-response SLA threshold in days."""
        return self._sla_days

    @staticmethod
    def days_since_submission(
        submitted_at: datetime, *, now: datetime | None = None
    ) -> int:
        """Whole days elapsed since ``submitted_at`` (never negative).

        ``now`` defaults to the current UTC time; passing it keeps the helper pure
        and testable. Both timestamps are treated as UTC.
        """
        current = now or datetime.now(UTC)
        if submitted_at.tzinfo is None:
            submitted_at = submitted_at.replace(tzinfo=UTC)
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        delta = current - submitted_at
        return max(0, delta.days)

    @staticmethod
    def is_likely_ghosted(
        days_since_submission: int, *, sla_days: int = DEFAULT_GHOST_SLA_DAYS
    ) -> bool:
        """True when silence has crossed the no-response SLA threshold (#192).

        A static helper so it is callable both on the class (``SilenceService
        .is_likely_ghosted(days)``) and as a pure function; ``sla_days`` overrides
        the default threshold when a campaign configures a different SLA.
        """
        return int(days_since_submission) >= int(sla_days)
