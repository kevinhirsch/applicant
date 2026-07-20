"""Source-reliability scoring and labelling (pure, no IO).

Given a discovery source key and optional yield_stats from the last run,
this module produces a deterministic reliability tier, score, label, and
human-readable detail string. It is the authoritative reference for how
the engine judges each source's trustworthiness.
"""

from __future__ import annotations

from applicant.core.rules.underdelivery import source_shortfall_message

#: Mapping of source-key prefix to reliability tier.
#: sample → high (in-process, always available)
#: jobspy:* → medium (network-backed, depends on board uptime)
#: searxng → medium (metasearch, depends on operator config)
#: rss:* → medium (feed-backed, depends on feed availability)
#: unknown → medium (conservative default)
SOURCE_TIERS: dict[str, str] = {
    "sample": "high",
    "jobspy": "medium",
    "searxng": "medium",
    "rss": "medium",
}

#: Tier baseline scores used when no yield_stats are available.
_TIER_BASELINES: dict[str, float] = {
    "high": 1.0,
    "medium": 0.75,
    "low": 0.5,
}

#: Status → score mapping for last_run outcomes.
_STATUS_SCORES: dict[str, float] = {
    "ok": 1.0,
    "empty": 0.5,
    "rate_limited": 0.3,
    "error": 0.0,
}


def _match_prefix(source_key: str) -> str | None:
    """Return the matching prefix key from SOURCE_TIERS or None."""
    key = (source_key or "").strip()
    if not key:
        return None
    prefix, _, tail = key.partition(":")
    if not tail:
        prefix, tail = "", prefix
    # Check if the prefix matches a tier key
    if prefix and prefix in SOURCE_TIERS:
        return prefix
    # Check if the whole key (no colon) matches a tier key
    if not prefix and tail in SOURCE_TIERS:
        return tail
    return None


def reliability_tier(source_key: str) -> str:
    """Return 'high', 'medium', or 'low' based on source key prefix.

    ``sample`` → 'high'; ``jobspy:*``, ``searxng``, ``rss:*`` → 'medium';
    unknown or empty → 'medium' (conservative default).
    """
    prefix = _match_prefix(source_key)
    if prefix is not None:
        return SOURCE_TIERS[prefix]
    return "medium"  # conservative default for unknown


def reliability_score(source_key: str, yield_stats: dict | None = None) -> float:
    """Return 0.0-1.0 reliability score.

    If yield_stats contains last_run with a known status, use that status score.
    Otherwise, fallback to tier baseline.
    """
    tier = reliability_tier(source_key)
    baseline = _TIER_BASELINES.get(tier, 0.75)

    if not yield_stats or not isinstance(yield_stats, dict):
        return baseline

    last_run = yield_stats.get("last_run")
    if not last_run or not isinstance(last_run, dict):
        return baseline

    status = last_run.get("status")
    if status in _STATUS_SCORES:
        return _STATUS_SCORES[status]

    # Unknown status string → tier baseline
    return baseline


def reliability_label(source_key: str, yield_stats: dict | None = None) -> str:
    """Return human-readable label: 'High', 'Medium', or 'Low'.

    Based on combined score thresholds: >=0.8 → High, >=0.4 → Medium, else Low.
    """
    score = reliability_score(source_key, yield_stats)
    if score >= 0.8:
        return "High"
    if score >= 0.4:
        return "Medium"
    return "Low"


def reliability_detail(source_key: str, yield_stats: dict | None = None) -> str:
    """Return a human-readable detail string about the source type.

    Appends last-run shortfall info if yield_stats has a non-ok status.
    """
    key = (source_key or "").strip()
    prefix, _, tail = key.partition(":")
    if not tail:
        prefix, tail = "", key

    if prefix == "" and tail == "sample":
        detail = "In-process data source (always available)"
    elif prefix == "jobspy":
        detail = "Network-backed source (reliability depends on board uptime)"
    elif prefix == "" and tail == "searxng":
        detail = "Metasearch source (depends on operator configuration)"
    elif prefix == "rss":
        detail = "RSS feed source (depends on feed availability)"
    else:
        detail = "Unknown source type"

    # Append last-run shortfall if non-ok
    if yield_stats and isinstance(yield_stats, dict):
        last_run = yield_stats.get("last_run")
        if last_run and isinstance(last_run, dict):
            status = last_run.get("status")
            if status and status != "ok":
                error = last_run.get("error")
                shortfall = source_shortfall_message(source_key, status, error=error)
                detail = f"{detail} — {shortfall}"

    return detail


def source_reliability(source_key: str, yield_stats: dict | None = None) -> dict:
    """Return a dict {source_key, tier, score, label, detail} aggregating all above."""
    return {
        "source_key": source_key,
        "tier": reliability_tier(source_key),
        "score": reliability_score(source_key, yield_stats),
        "label": reliability_label(source_key, yield_stats),
        "detail": reliability_detail(source_key, yield_stats),
    }
