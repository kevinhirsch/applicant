"""Real-postings validation gate for discovery ATS sources (NFR-EXT-1).

Kevin's explicit rule: "verified data sources that actually serve real jobs" is a
REQUIREMENT for adding ANY discovery source, not a nice-to-have. This module is the
ONE place that decides whether a candidate board's raw response counts as real
postings, and it is the shared enforcement point for both:

- the runtime "add a board" API path (``DiscoveryService.add_board``), which
  rejects a token/slug whose response doesn't shape-validate as real postings —
  not merely an empty list; and
- the offline pre-deploy check (``scripts/validate_discovery_boards.py``) an
  operator (or a future session widening discovery reach) runs BEFORE appending a
  new token to ``DISCOVERY_GREENHOUSE_BOARDS`` / ``DISCOVERY_LEVER_COMPANIES`` /
  ``DISCOVERY_ASHBY_ORGS`` / ``DISCOVERY_SMARTRECRUITERS_COMPANIES``.

A response counts as "real postings" only when it is non-empty AND at least one row
has BOTH a plausible title and a plausible identity/URL signal — an empty array, a
404-turned-``[]``, or a shape with no usable rows (e.g. an HTML error page that
happens to coerce to ``{}``) all fail closed, never silently pass.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceValidationResult:
    """Outcome of a real-postings check for one candidate ATS board.

    ``posting_count`` is the number of rows that PASSED the shape check (never the
    raw row count) — callers should treat this as the honest "real postings found"
    number, e.g. for ``DiscoveryService.add_board``'s response payload.
    """

    ok: bool
    posting_count: int
    reason: str = ""


#: Per-provider (title-field, identity/URL-field) shape expectations — the minimum
#: a raw row must carry to count as a REAL posting rather than noise/a malformed
#: row. SmartRecruiters' postings-LIST endpoint has no direct URL field (only an
#: ``id`` the public listing URL is built from, see ``_map_smartrecruiters_posting``
#: in ``jobspy_searxng.py``), so its second tuple checks for that identity key
#: instead of a literal URL.
PROVIDER_SHAPES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "greenhouse": (("title",), ("absolute_url",)),
    "lever": (("text",), ("hostedUrl", "applyUrl")),
    "ashby": (("title",), ("jobUrl", "applyUrl")),
    "smartrecruiters": (("name",), ("id",)),
    # Workday's CXS list rows carry a relative "externalPath" (the public URL is
    # synthesized from host/site + this path, see ``_map_workday_job``), not an
    # absolute URL -- same "identity field, not literal URL" allowance as
    # SmartRecruiters' ``id`` above.
    "workday": (("title",), ("externalPath",)),
    # Remote-job aggregators (EPIC BREADTH) -- single global feeds, not per-company
    # boards, but the same real-postings shape check applies.
    "remoteok": (("position",), ("url", "apply_url")),
    "remotive": (("title",), ("url",)),
    "workingnomads": (("title",), ("url",)),
}


def validate_postings_shape(
    rows: object, *, title_keys: tuple[str, ...], url_keys: tuple[str, ...]
) -> SourceValidationResult:
    """Gate a raw provider response: non-empty AND real-posting-shaped rows.

    Never raises — a malformed ``rows`` (not a list, or rows that aren't dicts)
    degrades to a clean rejection so a candidate that 404s into an unexpected shape
    fails closed instead of crashing the validator or (worse) the caller.
    """
    if not isinstance(rows, list) or not rows:
        return SourceValidationResult(False, 0, "empty response (no postings)")
    valid = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        has_title = any(row.get(k) for k in title_keys)
        has_identity = any(row.get(k) for k in url_keys)
        if has_title and has_identity:
            valid += 1
    if valid == 0:
        return SourceValidationResult(
            False,
            len(rows),
            "rows present but none had both a title and a URL/identity field "
            "-- not real postings",
        )
    return SourceValidationResult(True, valid, "")


def validate_provider_rows(provider: str, rows: object) -> SourceValidationResult:
    """Shape-validate ``rows`` for a known provider key (see ``PROVIDER_SHAPES``).

    An unrecognized ``provider`` fails closed (never silently "passes" a source
    type this gate doesn't know how to validate).
    """
    shape = PROVIDER_SHAPES.get(provider)
    if shape is None:
        return SourceValidationResult(False, 0, f"unknown provider '{provider}'")
    title_keys, url_keys = shape
    return validate_postings_shape(rows, title_keys=title_keys, url_keys=url_keys)
