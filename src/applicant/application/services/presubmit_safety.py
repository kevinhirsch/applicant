"""Pre-submit safety checks — scam/ghost-job detection, duplicate cooldown.

Each check raises ``PresubmitBlock`` with a user-facing reason when the
application should not proceed.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
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


# ---------------------------------------------------------------------------
# Issue #368 — Duplicate-application cooldown guard
# ---------------------------------------------------------------------------

#: Default window in days during which a repeat application to the same
#: (company, role) is blocked.
_DEFAULT_DUPLICATE_COOLDOWN_DAYS = 30


def _normalized_title(title: str) -> str:
    """Normalize a job title for fuzzy comparison.

    Strips whitespace/punctuation and lowercases so minor variations
    (e.g. "Software Engineer II" vs "Software Engineer 2") still match.
    """
    import re

    t = title.strip().lower()
    # Normalize roman numerals and common variations.
    t = re.sub(r"\bii\b", "2", t)
    t = re.sub(r"\biii\b", "3", t)
    t = re.sub(r"\biv\b", "4", t)
    t = re.sub(r"\bsr\b", "senior", t)
    t = re.sub(r"\bjr\b", "junior", t)
    t = re.sub(r"[^a-z0-9\s]", "", t)
    return re.sub(r"\s+", " ", t).strip()


def check_duplicate_application(
    campaign_id: Any,
    posting: Any,
    storage: Any,
    *,
    cooldown_days: int = _DEFAULT_DUPLICATE_COOLDOWN_DAYS,
    reference_date: date | None = None,
) -> None:
    """Raise ``PresubmitBlock`` if the same (company, role) was already applied
    to within the cooldown window.

    Scans existing applications for the campaign that share the same company
    and a normalized role title. Terminal/completed applications count toward
    the cooldown; in-flight applications do not (they are being worked on now).
    """
    ref = reference_date or datetime.now(UTC).date()
    cutoff = ref - timedelta(days=cooldown_days)
    company = (posting.company or "").strip().lower()
    if not company:
        return
    new_title_norm = _normalized_title(posting.title or "")
    if not new_title_norm:
        return
    from applicant.core.state_machine import ApplicationState

    # BUGFIX: this set literal referenced ``ApplicationState.CONVERTED``, which has
    # never existed on the enum (confirmed by a repo-wide grep — no other reference
    # anywhere) — so building this set raised ``AttributeError`` on EVERY call,
    # before the function could ever reach the comparison logic below. The guard
    # has therefore never actually run. "Already applied" here means the
    # application actually went out: SUBMITTED_BY_USER/FINISHED_BY_ENGINE plus
    # every state reachable ONLY via one of those (the G16 post-submission
    # lifecycle, state_machine.py) — an application that has since moved on to
    # being tracked/rejected/ghosted/archived still counts as a duplicate, not
    # just the instant right after submission.
    terminal_states = {
        ApplicationState.SUBMITTED_BY_USER,
        ApplicationState.FINISHED_BY_ENGINE,
        ApplicationState.POST_SUBMISSION,
        ApplicationState.AWAITING_RESPONSE,
        ApplicationState.REJECTED,
        ApplicationState.GHOSTED,
        ApplicationState.FOLLOWING_UP,
        ApplicationState.ARCHIVED,
    }
    for app in storage.applications.list_for_campaign(campaign_id):
        existing_posting = storage.postings.get(app.posting_id)
        if existing_posting is None:
            continue
        if (existing_posting.company or "").strip().lower() != company:
            continue
        if _normalized_title(existing_posting.title or "") != new_title_norm:
            continue
        if app.status not in terminal_states:
            continue
        app_created = getattr(app, "created_at", None)
        if app_created is None:
            continue
        if hasattr(app_created, "date"):
            app_date = app_created.date()
        else:
            continue
        if app_date >= cutoff:
            raise PresubmitBlock(
                f"Already applied to {existing_posting.company} for '{existing_posting.title}' "
                f"within the last {cooldown_days} days (applied on {app_date}).",
                check="duplicate_cooldown",
            )


# ---------------------------------------------------------------------------
# Issue #369 — Per-company application volume cap
# ---------------------------------------------------------------------------

#: Default maximum number of applications per company per day.
_DEFAULT_MAX_APPS_PER_COMPANY_PER_DAY = 3


def check_per_company_volume_cap(
    campaign_id: Any,
    posting: Any,
    storage: Any,
    *,
    max_per_day: int = _DEFAULT_MAX_APPS_PER_COMPANY_PER_DAY,
    reference_date: date | None = None,
) -> None:
    """Raise ``PresubmitBlock`` if the daily per-company volume cap would be
    exceeded by applying to this posting.

    Counts all applications (any status) for the same company started on the
    reference date. When adding this one would exceed ``max_per_day``, block.
    """
    ref = reference_date or datetime.now(UTC).date()
    company = (posting.company or "").strip().lower()
    if not company:
        return
    count = 0
    for app in storage.applications.list_for_campaign(campaign_id):
        existing_posting = storage.postings.get(app.posting_id)
        if existing_posting is None:
            continue
        if (existing_posting.company or "").strip().lower() != company:
            continue
        app_created = getattr(app, "created_at", None)
        if app_created is None:
            continue
        if hasattr(app_created, "date"):
            app_date = app_created.date()
        else:
            continue
        if app_date == ref:
            count += 1
    if count >= max_per_day:
        raise PresubmitBlock(
            f"Daily application cap for {posting.company} reached "
            f"({count} applied today, max {max_per_day}).",
            check="per_company_volume",
        )


# ---------------------------------------------------------------------------
# Issue #371 — Eligibility filter (work-authorization)
# ---------------------------------------------------------------------------

#: Keywords in job descriptions that indicate a requirement for visa
#: sponsorship or security clearance.
_SPONSORSHIP_KEYWORDS = (
    "sponsorship",
    "visa sponsorship",
    "work authorization",
    "must be authorized",
    "green card",
    "h1b",
    "h-1b",
    "work permit",
    "must have permanent",
    "no sponsorship",
    "will not sponsor",
    "unable to sponsor",
    "must be a us person",
    "must be a us citizen",
    "must be a citizen",
    "us citizenship",
    "security clearance",
    "top secret clearance",
    "secret clearance",
    "government clearance",
    "clearance required",
    "must hold clearance",
    "eligible for clearance",
    "itear",
    "export control",
    "itar",
)


def _extract_work_authorization(storage: Any, campaign_id: Any) -> dict[str, bool]:
    """Extract work-authorization signals from the campaign's onboarding intake
    and attribute cloud.

    Returns a dict with keys like:
      - ``needs_sponsorship``: True if the user needs visa sponsorship
      - ``has_clearance``: True if the user holds a security clearance
      - ``citizenship``: the user's stated citizenship if available
    """
    result: dict[str, bool] = {}
    # Check the onboarding intake.
    profile = storage.onboarding_profiles.get_for_campaign(campaign_id)
    if profile is not None:
        intake = profile.intake or {}
        work_auth = intake.get("work_authorization") or {}
        if isinstance(work_auth, dict):
            result["needs_sponsorship"] = bool(
                work_auth.get("needs_sponsorship", False)
                or work_auth.get("requires_sponsorship", False)
                or work_auth.get("visa_sponsorship_required", False)
            )
            result["has_clearance"] = bool(
                work_auth.get("has_security_clearance", False)
                or work_auth.get("security_clearance", False)
            )
            result["citizenship"] = str(
                work_auth.get("citizenship")
                or work_auth.get("work_authorization_status")
                or ""
            )
    # Fall back to attributes.
    if not result.get("citizenship"):
        for attr in storage.attributes.list_for_campaign(campaign_id):
            name_lower = (attr.name or "").lower()
            if "citizenship" in name_lower or "work authorization" in name_lower:
                result["citizenship"] = attr.value
            if "sponsorship" in name_lower or "visa" in name_lower:
                result["needs_sponsorship"] = (
                    attr.value.strip().lower()
                    in ("yes", "true", "required", "needed")
                )
            if "clearance" in name_lower or "security" in name_lower:
                result["has_clearance"] = (
                    attr.value.strip().lower()
                    in ("yes", "true", "secret", "top secret")
                )
    return result


def check_eligibility(
    campaign_id: Any,
    posting: Any,
    storage: Any,
) -> None:
    """Raise ``PresubmitBlock`` if the posting has sponsorship or clearance
    requirements that conflict with the user's stated work authorization.

    Uses the onboarding intake and attribute cloud to determine the user's
    work-authorization status, then scans the posting's description for
    keywords indicating incompatible requirements.
    """
    work_auth = _extract_work_authorization(storage, campaign_id)
    jd_lower = (posting.description or "").lower()
    title_lower = (posting.title or "").lower()
    combined = f"{title_lower} {jd_lower}"

    # Check sponsorship requirements.
    needs_sponsorship = work_auth.get("needs_sponsorship", False)
    requires_sponsorship_phrase = any(
        kw in combined for kw in _SPONSORSHIP_KEYWORDS
    )
    if requires_sponsorship_phrase and needs_sponsorship:
        raise PresubmitBlock(
            "Posting mentions sponsorship/work-authorization requirements "
            "and your profile indicates you need visa sponsorship.",
            check="eligibility_sponsorship",
        )
    # When the posting explicitly says "no sponsorship" and the user needs it,
    # also block.
    no_sponsorship_phrases = (
        "no sponsorship",
        "will not sponsor",
        "unable to sponsor",
        "must be a us person",
        "must be a us citizen",
        "must be a citizen",
    )
    if needs_sponsorship and any(p in combined for p in no_sponsorship_phrases):
        raise PresubmitBlock(
            "Posting explicitly states no visa sponsorship is available, "
            "and your profile indicates you need sponsorship.",
            check="eligibility_no_sponsorship",
        )

    # Check clearance requirements.
    has_clearance = work_auth.get("has_clearance", False)
    clearance_phrases = (
        "security clearance",
        "clearance required",
        "must hold clearance",
        "top secret",
        "secret clearance",
    )
    clearance_required = any(p in combined for p in clearance_phrases)
    if clearance_required and not has_clearance:
        raise PresubmitBlock(
            "Posting requires a security clearance, and your profile "
            "does not indicate you hold one.",
            check="eligibility_clearance",
        )
