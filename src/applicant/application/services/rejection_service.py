"""RejectionService — post-submission rejection detection (#191, FR-LEARN-2).

The engine can detect email-verification gates and send outbound notices, but
historically had no way to recognise that a submitted application was *rejected*.
This service closes that gap with a pure, dependency-free classifier over two
signal sources:

* an inbound mailbox notice (``classify_message``) — the body of an email the
  candidate received about a submitted application, and
* an ATS status page (``classify_status_page``) — the visible text of the
  application's status page in the ATS portal.

Both return the recognised post-submission outcome string (currently only
``"rejected"``) or ``None`` when no negative signal is present. A detected
rejection is recorded as a negative :class:`OutcomeEvent` so the learning loop
(FR-LEARN-2) can down-weight the source/role signature that produced it.

Pure and hermetic: no IO, no LLM, no network — the heuristics are deterministic
phrase matches so the classifier is testable in CI without a real mailbox.
"""

from __future__ import annotations

from applicant.core.entities.outcome_event import OUTCOME_TYPES

#: Phrases that, when present in an inbound message body, signal a rejection.
#: Kept conservative (high-precision) so an ambiguous "thanks for applying" alone
#: does not flip an application to rejected — the learning loop trusts these.
_REJECTION_MESSAGE_MARKERS: tuple[str, ...] = (
    "move forward with other candidates",
    "moving forward with other candidates",
    "decided to move forward with other",
    "will not be moving forward",
    "not be moving forward with your application",
    "we have decided not to proceed",
    "decided not to move forward",
    "unfortunately, we will not",
    "unfortunately we will not",
    "we regret to inform you",
    "not selected for this position",
    "not be progressing your application",
    "pursue other candidates",
    "filled this position",
    "position has been filled",
)

#: Phrases an ATS status page shows when an application is closed/rejected.
_REJECTION_STATUS_MARKERS: tuple[str, ...] = (
    "no longer under consideration",
    "not selected",
    "application closed",
    "position filled",
    "not moving forward",
    "candidate withdrawn",
    "rejected",
    "declined",
)

REJECTED = "rejected"


class RejectionService:
    """Classify inbound notices / status pages as rejection outcomes (#191)."""

    @staticmethod
    def classify_message(text: str | None) -> str | None:
        """Classify an inbound email/message body.

        Returns ``"rejected"`` when the body contains a high-precision rejection
        marker, else ``None`` (not a rejection signal).
        """
        low = (text or "").lower()
        if any(marker in low for marker in _REJECTION_MESSAGE_MARKERS):
            return REJECTED
        return None

    @staticmethod
    def classify_status_page(text: str | None) -> str | None:
        """Classify the visible text of an ATS application status page.

        Returns ``"rejected"`` when the page reads as closed / no-longer-under-
        consideration, else ``None``.
        """
        low = (text or "").lower()
        if any(marker in low for marker in _REJECTION_STATUS_MARKERS):
            return REJECTED
        return None

    @staticmethod
    def is_rejection(outcome: str | None) -> bool:
        """True when ``outcome`` is the recognised rejection outcome type."""
        return outcome == REJECTED and REJECTED in OUTCOME_TYPES
