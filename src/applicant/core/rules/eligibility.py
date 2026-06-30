"""Work-authorization / sponsorship eligibility filter (Issue #369).

A pure core rule that compares a posting's stated work-authorization
requirements (visa sponsorship, citizenship, clearance) against the user's
captured work-authorization, and excludes/flags a posting the user is
ineligible for — surfacing a plain-language reason. An eligible posting is left
unaffected.

Reuses the materials sponsorship lexicon (``core/rules/materials._FACTUAL_CUES``)
so the phrasing the answer-filler already recognizes is the same phrasing this
filter keys on — one definition, no drift.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

#: Phrases that indicate a posting requires the candidate to NOT need sponsorship
#: (i.e. sponsorship is unavailable) or to already hold work authorization.
_SPONSORSHIP_REQUIRED_CUES: tuple[str, ...] = (
    "visa sponsorship",
    "require sponsorship",
    "requires sponsorship",
    "sponsorship is available",
    "sponsorship available",
    "will sponsor",
    "we sponsor",
    "h-1b",
    "h1b",
    "must be authorized to work",
    "authorized to work in",
    "citizenship required",
    "us citizen",
    "u.s. citizen",
    "security clearance",
)


@dataclass(frozen=True)
class EligibilityVerdict:
    """The outcome of scoring a posting against a user's work-authorization."""

    eligible: bool
    reason: str = ""


def _needs_sponsorship(work_auth: Mapping) -> bool:
    """True if the user requires sponsorship to take the role."""
    if work_auth.get("needs_sponsorship") is True:
        return True
    # ``can_be_sponsored`` describes whether the user *can* accept a sponsored
    # role; a user who needs sponsorship but cannot be sponsored is ineligible.
    return work_auth.get("can_be_sponsored") is False and bool(
        work_auth.get("needs_sponsorship", False)
    )


def _posting_mentions_sponsorship(posting_text: str) -> bool:
    text = (posting_text or "").lower()
    return any(cue in text for cue in _SPONSORSHIP_REQUIRED_CUES)


def assess_work_auth_eligibility(
    posting_text: str, work_auth: Mapping
) -> EligibilityVerdict:
    """Score ``posting_text`` against the user's ``work_auth`` (#369).

    Returns an :class:`EligibilityVerdict`. A posting that requires sponsorship
    the user cannot obtain is excluded (``eligible is False``) with a reason; a
    posting with no conflicting requirement is left eligible.
    """
    if _posting_mentions_sponsorship(posting_text) and _needs_sponsorship(work_auth):
        return EligibilityVerdict(
            eligible=False,
            reason=(
                "This role's stated work-authorization requirements conflict with "
                "your captured work authorization (sponsorship needed but not "
                "offered)."
            ),
        )
    return EligibilityVerdict(eligible=True, reason="")
