"""OutcomeEvent entity — submission/conversion event (FR-LOG-4, FR-LEARN-2)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from applicant.core.ids import ApplicationId, OutcomeEventId


class OutcomeSource(str, Enum):
    AUTO = "auto"  # auto-detected from confirmation page
    MANUAL = "manual"  # one-tap "mark submitted"


#: The recognized post-submission outcome catalogue (#190, FR-LOG-4 / FR-LEARN-2).
#: An application's lifecycle continues past submit: a recorded ``submitted`` event
#: can be followed by a real-world outcome (a rejection, an interview invite, the
#: application going silent/ghosted, or an offer). These feed the learning loop
#: (FR-LEARN-2) — a negative outcome down-weights its source/role signature; a
#: positive one (interview/offer) up-weights it. ``OUTCOME_TYPES`` is the single
#: source of truth for which strings are valid :class:`OutcomeEvent.type` values.
OUTCOME_TYPES: frozenset[str] = frozenset(
    {
        "submitted",  # the application was submitted (manual or auto-detected)
        "converted",  # legacy alias used by the confirmation-page detector
        "rejected",  # a rejection notice / status was detected (#191)
        "interview_invited",  # an interview invitation arrived
        "ghosted",  # no response past the silence SLA (#192)
        "offer",  # an offer was extended
    }
)


def is_recognized_outcome(outcome_type: str) -> bool:
    """True when ``outcome_type`` is a recognized post-submission outcome (#190)."""
    return outcome_type in OUTCOME_TYPES


@dataclass(frozen=True)
class OutcomeEvent:
    """A submission/conversion event; source distinguishes auto vs manual."""

    id: OutcomeEventId
    application_id: ApplicationId
    type: str  # e.g. "submitted", "converted"
    source: OutcomeSource = OutcomeSource.AUTO
