"""OutcomeEvent entity — submission/conversion event (FR-LOG-4, FR-LEARN-2)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from applicant.core.ids import ApplicationId, OutcomeEventId


class OutcomeSource(str, Enum):
    AUTO = "auto"  # auto-detected from confirmation page
    MANUAL = "manual"  # one-tap "mark submitted"


@dataclass(frozen=True)
class OutcomeEvent:
    """A submission/conversion event; source distinguishes auto vs manual."""

    id: OutcomeEventId
    application_id: ApplicationId
    type: str  # e.g. "submitted", "converted"
    source: OutcomeSource = OutcomeSource.AUTO
