"""OutcomeLogging driving port (FR-LOG-4).

One-tap "mark submitted" when auto-detection cannot confirm submission; events
feed FR-LEARN-2 (real conversion).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from applicant.core.entities.outcome_event import OutcomeEvent
from applicant.core.ids import ApplicationId


@runtime_checkable
class OutcomeLoggingPort(Protocol):
    """Inbound port for recording submission/conversion outcomes."""

    def mark_submitted(self, application_id: ApplicationId) -> OutcomeEvent:
        """Manually mark an application submitted (FR-LOG-4)."""
        ...
