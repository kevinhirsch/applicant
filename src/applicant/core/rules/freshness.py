"""Posting-freshness display rule (product ask: "the date it was posted really
indicates whether there's actual value in chasing it down").

Pure, deterministic, no IO — given a posting's two freshness timestamps
(``JobPosting.date_posted`` / ``JobPosting.first_seen``, see
``core.entities.job_posting``), produces the plain-language cue the Pending
Reviews / Digest / Top New Matches surfaces render next to a role's fit score:
a label, a human relative-age string, and a "stale" flag for postings old
enough that a high fit score alone is likely misleading (it may well be
filled by now).

Honesty invariant (H-series): ``date_posted`` is the board-reported post date
(from jobspy/Greenhouse/Lever); ``first_seen`` is only when *our* discovery
first noticed the posting, which can lag the real post date. When only
``first_seen`` is available the label says **"First seen"**, never "Posted" —
this rule must never imply a posted date the engine doesn't actually have.
"""

from __future__ import annotations

from datetime import UTC, datetime

#: A posting older than this many days is flagged stale: a great-fit role
#: posted this long ago is, per the product rationale, more likely already
#: filled — the UI dims/flags it rather than letting a high score alone read
#: as "definitely still worth chasing".
STALE_AFTER_DAYS = 21


def posting_freshness(
    date_posted: datetime | None,
    first_seen: datetime | None,
    *,
    now: datetime | None = None,
) -> dict | None:
    """Freshness display fields for one posting, or ``None`` when unknown.

    Returns ``None`` (never a dict with fabricated/placeholder values) when
    both timestamps are absent — legacy rows discovery never stamped. Callers
    must render nothing for a ``None`` result (no "Invalid Date"/"NaN days
    ago"), not degrade to a guess.

    On a truthy result, the dict always carries all four keys:

    - ``posted_date``: ISO-8601 timestamp of whichever reference was used.
    - ``posted_label``: ``"Posted"`` (real board date) or ``"First seen"``
      (discovery-only fallback) — which one is used, honestly labeled.
    - ``posted_relative``: human string, e.g. ``"today"`` / ``"3 days ago"`` /
      ``"2 months ago"``.
    - ``posted_stale``: ``True`` once the reference is older than
      :data:`STALE_AFTER_DAYS`.
    """
    ref = date_posted if date_posted is not None else first_seen
    if ref is None:
        return None
    is_real_posted_date = date_posted is not None

    now = now if now is not None else datetime.now(UTC)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)

    # Clamp negative ages (clock skew / a scraped date in the future) to 0
    # rather than surface a nonsensical "-2 days ago".
    age_days = max(0, int((now - ref).total_seconds() // 86400))

    return {
        "posted_date": ref.isoformat(),
        "posted_label": "Posted" if is_real_posted_date else "First seen",
        "posted_relative": _relative_days(age_days),
        "posted_stale": age_days > STALE_AFTER_DAYS,
    }


def _relative_days(age_days: int) -> str:
    """Plain-language age string, coarsening as the age grows (never decimals)."""
    if age_days <= 0:
        return "today"
    if age_days == 1:
        return "1 day ago"
    if age_days < 30:
        return f"{age_days} days ago"
    if age_days < 365:
        months = max(1, age_days // 30)
        return f"{months} month{'s' if months != 1 else ''} ago"
    years = max(1, age_days // 365)
    return f"{years} year{'s' if years != 1 else ''} ago"
