"""FollowUpService — post-submission follow-up outreach (#193, FR-LOG-4).

Outbound notification infrastructure exists, but there was no generation of a
thank-you / check-in follow-up, no detection that a follow-up is *warranted*, and
no review path for the drafted message. This service adds:

* ``followup_is_due`` — a deterministic SLA over days-since-submission deciding
  whether a check-in is warranted (a too-soon follow-up reads as pestering), and
* ``draft_followup`` — a plain-language, review-gated draft (never auto-sent): the
  message is produced for the user to review and send, honouring the engine's
  review-before-act posture.

The draft is built from the candidate's own facts only (role + company); it never
fabricates outcome claims. Pure and hermetic — no IO, no LLM required.
"""

from __future__ import annotations

#: Days after submission before a check-in follow-up is warranted. Soon enough to
#: stay top-of-mind, late enough not to pester (a week+ of silence).
DEFAULT_FOLLOWUP_DUE_DAYS = 10


class FollowUpService:
    """Draft and time post-submission follow-up outreach (#193)."""

    def __init__(self, *, due_after_days: int = DEFAULT_FOLLOWUP_DUE_DAYS) -> None:
        self._due_after_days = int(due_after_days)

    @property
    def due_after_days(self) -> int:
        """Days after submission before a follow-up is considered due."""
        return self._due_after_days

    @staticmethod
    def followup_is_due(
        days_since_submission: int, *, due_after_days: int = DEFAULT_FOLLOWUP_DUE_DAYS
    ) -> bool:
        """True when enough time has passed to warrant a check-in (#193).

        A static helper so it is callable both on the class (``FollowUpService
        .followup_is_due(days)``) and as a pure function; ``due_after_days``
        overrides the default threshold.
        """
        return int(days_since_submission) >= int(due_after_days)

    @staticmethod
    def draft_followup(
        *, role: str = "the role", company: str = "your team"
    ) -> str:
        """Draft a plain-language check-in message for the user to review and send.

        Built from the candidate's own facts (role + company) — no fabricated
        outcome claims. The message is returned for review; it is never auto-sent.
        """
        role = (role or "the role").strip() or "the role"
        company = (company or "your team").strip() or "your team"
        return (
            f"Hi,\n\n"
            f"I wanted to follow up on my application for {role} at {company}. "
            f"I remain very interested in the opportunity and would welcome the "
            f"chance to discuss how I can contribute. Please let me know if there "
            f"is anything further I can provide.\n\n"
            f"Thank you for your time and consideration."
        )
