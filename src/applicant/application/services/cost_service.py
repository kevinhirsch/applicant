"""CostService — cost & pace guardrails read model (P1-6).

Turns the LLM token usage ``AgentLoop`` durably folds into ``agent_runs.stats``
(see ``agent_loop.py``'s ``_drain_usage_stats``, fed by the shared ``llm``
adapter's ``usage_recorder`` — ``adapters/llm/openai_compatible.py``) into the
numbers the front door surfaces:

* **today** — applications acted on today vs. the daily target/hard cap
  (``core.entities.campaign``), an estimated dollar spend for today, and a
  rough "≈$Y per application" average;
* **monthly** — month-to-date spend and a linear whole-month projection.

Every dollar figure here is explicitly an ESTIMATE (H-series honesty): the
engine cannot know a provider's live per-model price list without another
network call, so these are derived from a configured $/1K-token rate, never
exact billing. When NO call today reported usage at all, ``usage_reported`` is
False so the caller can say so honestly instead of implying "free".
"""

from __future__ import annotations

from datetime import UTC, datetime, time

from applicant.core.entities.campaign import THROUGHPUT_HARD_CAP, Campaign
from applicant.core.ids import CampaignId
from applicant.core.rules.cost_estimate import (
    average_cost_per_application,
    days_in_month,
    project_monthly_usd,
)

#: Keys ``AgentLoop._drain_usage_stats`` writes into ``agent_runs.stats`` (P1-6).
_USAGE_STATS_KEYS = ("tokens_in", "tokens_out", "cost_usd_estimate", "llm_calls")


class CostService:
    def __init__(self, storage) -> None:
        self._storage = storage

    def _totals(self, campaign_id: CampaignId, start: datetime, end: datetime) -> dict:
        return self._storage.agent_runs.sum_stats_between(
            campaign_id, start, end, _USAGE_STATS_KEYS
        )

    def today_summary(self, campaign: Campaign, now: datetime | None = None) -> dict:
        """Applications-today vs. the daily target/hard cap, plus estimated spend."""
        now = now or datetime.now(UTC)
        day = now.date()
        start = datetime.combine(day, time.min)
        end = datetime.combine(day, time.max)
        totals = self._totals(campaign.id, start, end)
        applications_today = int(
            self._storage.agent_runs.count_pipelines_started_on(campaign.id, day)
        )
        cost = float(totals.get("cost_usd_estimate", 0.0))
        calls = int(totals.get("llm_calls", 0))
        avg = average_cost_per_application(cost, applications_today)
        return {
            "applications_today": applications_today,
            "daily_target": int(campaign.throughput_target),
            "hard_cap": THROUGHPUT_HARD_CAP,
            "remaining_today": max(0, int(campaign.throughput_target) - applications_today),
            "tokens_in_today": int(totals.get("tokens_in", 0)),
            "tokens_out_today": int(totals.get("tokens_out", 0)),
            "cost_today_usd_estimate": round(cost, 4),
            "cost_per_application_usd_estimate": (
                round(avg, 4) if avg is not None else None
            ),
            "usage_reported": calls > 0,
        }

    def monthly_projection(self, campaign: Campaign, now: datetime | None = None) -> dict:
        """Month-to-date estimated spend + a linear projection for the whole month."""
        now = now or datetime.now(UTC)
        month_start = now.date().replace(day=1)
        start = datetime.combine(month_start, time.min)
        end = now.replace(tzinfo=None) if now.tzinfo else now
        totals = self._totals(campaign.id, start, end)
        cost = float(totals.get("cost_usd_estimate", 0.0))
        projected = project_monthly_usd(
            cost, now.day, days_in_month(now.year, now.month)
        )
        return {
            "month_to_date_usd_estimate": round(cost, 2),
            "projected_month_usd_estimate": round(projected, 2),
            "usage_reported": int(totals.get("llm_calls", 0)) > 0,
        }
