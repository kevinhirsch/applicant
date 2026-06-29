"""Pre-submit safety checks — scam/ghost-job detection.

Each check raises ``PresubmitBlock`` with a user-facing reason when the
application should not proceed.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from applicant.observability.logging import get_logger

log = get_logger(__name__)


class PresubmitBlock(Exception):
    """Raised when a presubmit safety check blocks an application."""

    def __init__(self, reason: str, *, check: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.check = check


# ---------------------------------------------------------------------------
# Issue #367 — Scam/ghost-job detection
# ---------------------------------------------------------------------------

#: Postings older than this many days are considered stale/ghost jobs.
_DEFAULT_MAX_LISTING_AGE_DAYS = 90
#: Postings with a description shorter than this many chars are suspicious.
_MIN_DESCRIPTION_CHARS = 50
#: Company names that look like generic/placeholder text (lowercase check).
_SUSPICIOUS_COMPANY_PATTERNS = (
    "confidential",
    "undisclosed",
    "hidden",
    "private",
    "n/a",
    "na",
    "---",
    "...",
)


def _listing_age_days(posting: Any, reference_date: date | None = None) -> int | None:
    """Return the estimated age of a posting in days, or None if unknown.

    Uses ``posting.rationale.get("discovered_at")`` if available (set by
    discovery), otherwise returns None so age-check only blocks when we have
    a timestamp.
    """
    raw = (posting.rationale or {}).get("discovered_at")
    if raw is None:
        return None
    try:
        discovered = datetime.fromisoformat(str(raw))
        if discovered.tzinfo is None:
            discovered = discovered.replace(tzinfo=UTC)
        ref = reference_date or datetime.now(UTC).date()
        return (ref - discovered.date()).days
    except (ValueError, TypeError):
        return None


def _company_reputation_signals(posting: Any) -> list[str]:
    """Return a list of warning signals about the company behind a posting.

    Checks for suspicious/placeholder company names and generic descriptions.
    """
    signals: list[str] = []
    company = (posting.company or "").strip().lower()
    if not company or company in _SUSPICIOUS_COMPANY_PATTERNS:
        signals.append("Company name is missing or appears to be a placeholder")
    description = (posting.description or "").strip()
    if description and len(description) < _MIN_DESCRIPTION_CHARS:
        signals.append(
            f"Job description is unusually short ({len(description)} chars)"
        )
    # Check for generic "we are hiring" bloat with no role-specific detail.
    if description and len(description) > 20:
        generic_phrases = [
            "we are looking for a talented",
            "we are hiring",
            "join our growing team",
            "we are seeking a",
        ]
        low_desc = description.lower()
        has_specifics = any(
            term in low_desc
            for term in [
                "skill",
                "experience",
                "responsibility",
                "qualification",
                "requirement",
                "year",
            ]
        )
        has_generic = any(phrase in low_desc for phrase in generic_phrases)
        if has_generic and not has_specifics:
            signals.append(
                "Description uses generic recruiting language with no role-specific detail"
            )
    return signals


def check_scam_or_ghost_job(
    posting: Any,
    *,
    max_age_days: int = _DEFAULT_MAX_LISTING_AGE_DAYS,
    reference_date: date | None = None,
) -> None:
    """Raise ``PresubmitBlock`` if the posting shows scam/ghost-job signals.

    Checks listing age (when a discovered_at timestamp is available) and
    company reputation signals (missing/placeholder company, thin description).
    """
    age = _listing_age_days(posting, reference_date)
    if age is not None and age > max_age_days:
        raise PresubmitBlock(
            f"Posting is {age} days old (max {max_age_days}); likely stale or a ghost job.",
            check="listing_age",
        )
    signals = _company_reputation_signals(posting)
    if signals:
        detail = "; ".join(signals)
        raise PresubmitBlock(
            f"Company reputation signals indicate potential scam/ghost job: {detail}",
            check="company_reputation",
        )
