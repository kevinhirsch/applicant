"""LLM cost & pace guardrail math (P1-6).

Pure, no I/O: turns captured token counts into a best-effort dollar figure and a
month-end projection. Every number this module produces is explicitly an
ESTIMATE — the engine has no way to know a provider's live per-model price list
without an extra network call, so callers must present these as estimates, never
as exact billing (H-series honesty: an approximation must never render as a fact).

The daily throughput **target**/**hard cap** guardrail itself
(``core.entities.campaign.clamp_throughput``/``THROUGHPUT_HARD_CAP``) already
lives in ``core/entities/campaign.py`` — this module is only the cost-side half
of "cost & pace guardrails".
"""

from __future__ import annotations

from datetime import date

#: Conservative default blended rate ($ per 1K tokens) used when the operator has
#: not tuned Settings to their actual provider's pricing. Deliberately NOT the
#: cheapest possible tier's price — a "never fear a runaway bill" guardrail should
#: round up, not down, when it has to guess.
DEFAULT_INPUT_PRICE_PER_1K_USD = 0.15
DEFAULT_OUTPUT_PRICE_PER_1K_USD = 0.60


def estimate_cost_usd(
    tokens_in: int,
    tokens_out: int,
    *,
    input_price_per_1k: float = DEFAULT_INPUT_PRICE_PER_1K_USD,
    output_price_per_1k: float = DEFAULT_OUTPUT_PRICE_PER_1K_USD,
) -> float:
    """Best-effort dollar estimate for one call's (or one day's) token usage.

    Negative token counts (should never happen, but a defensively-parsed provider
    body is not to be trusted) are clamped to zero rather than producing a
    negative "spend".
    """
    tin = max(0, int(tokens_in))
    tout = max(0, int(tokens_out))
    return (tin / 1000.0) * input_price_per_1k + (tout / 1000.0) * output_price_per_1k


def days_in_month(year: int, month: int) -> int:
    """Number of days in ``year``-``month`` (1-12), with no calendar dependency."""
    if month == 12:
        nxt = date(year + 1, 1, 1)
    else:
        nxt = date(year, month + 1, 1)
    return (nxt - date(year, month, 1)).days


def project_monthly_usd(month_to_date_usd: float, day_of_month: int, days_in_month_: int) -> float:
    """Linear projection: extrapolate month-to-date spend across the whole month.

    ``day_of_month``/``days_in_month_`` are supplied by the caller (rather than
    this module importing a real clock) so the projection stays pure and
    hermetically testable. The very first day of a month (``day_of_month <= 1``
    with nothing spent yet) can't meaningfully extrapolate — returns the
    month-to-date figure itself rather than dividing by a near-zero denominator
    into a wildly unstable number.
    """
    if day_of_month <= 0 or days_in_month_ <= 0:
        return max(0.0, float(month_to_date_usd))
    if day_of_month <= 1:
        return max(0.0, float(month_to_date_usd))
    return (float(month_to_date_usd) / day_of_month) * days_in_month_


def average_cost_per_application(total_cost_usd: float, applications: int) -> float | None:
    """Rough "≈$Y per application" figure — ``None`` when there is nothing to divide by.

    ``None`` (rather than 0.0) lets the caller render "not enough data yet"
    honestly instead of implying applications cost nothing today.
    """
    if applications <= 0:
        return None
    return max(0.0, float(total_cost_usd)) / applications
