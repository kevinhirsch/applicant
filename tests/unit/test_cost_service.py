"""Unit tests for CostService (P1-6 cost & pace guardrails read model).

Hermetic: builds ``agent_runs`` rows directly against ``InMemoryStorage`` (the
shape ``AgentLoop._drain_usage_stats`` writes — see agent_loop.py) rather than
driving a full tick, so these tests isolate the read-model math from the loop.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.cost_service import CostService
from applicant.core.entities.agent_run import AgentRun
from applicant.core.entities.campaign import THROUGHPUT_HARD_CAP, Campaign, RunMode
from applicant.core.ids import AgentRunId, CampaignId, new_id


def _make_campaign(storage, *, target=15):
    cid = CampaignId(new_id())
    storage.campaigns.add(
        Campaign(id=cid, name="C", run_mode=RunMode.CONTINUOUS, throughput_target=target)
    )
    return cid


def _add_run(storage, cid, *, timestamp, stats):
    storage.agent_runs.add(
        AgentRun(id=AgentRunId(new_id()), campaign_id=cid, timestamp=timestamp, stats=stats)
    )


@pytest.mark.unit
def test_today_summary_reports_zero_with_no_runs_yet():
    storage = InMemoryStorage()
    campaign = Campaign(id=_make_campaign(storage, target=15), name="C")
    svc = CostService(storage)
    now = datetime.now(UTC)
    summary = svc.today_summary(campaign, now)
    assert summary["applications_today"] == 0
    assert summary["daily_target"] == 15
    assert summary["hard_cap"] == THROUGHPUT_HARD_CAP
    assert summary["cost_today_usd_estimate"] == 0.0
    assert summary["cost_per_application_usd_estimate"] is None
    assert summary["usage_reported"] is False


@pytest.mark.unit
def test_today_summary_sums_the_days_runs_and_estimates_per_application_cost():
    storage = InMemoryStorage()
    cid = _make_campaign(storage, target=15)
    campaign = storage.campaigns.get(cid)
    now = datetime.now(UTC)
    _add_run(
        storage, cid, timestamp=now,
        stats={
            "pipelines_started": 2,
            "tokens_in": 1000,
            "tokens_out": 200,
            "cost_usd_estimate": 0.30,
            "llm_calls": 3,
        },
    )
    _add_run(
        storage, cid, timestamp=now,
        stats={
            "pipelines_started": 1,
            "tokens_in": 500,
            "tokens_out": 100,
            "cost_usd_estimate": 0.10,
            "llm_calls": 1,
        },
    )
    svc = CostService(storage)
    summary = svc.today_summary(campaign, now)
    assert summary["applications_today"] == 3
    assert summary["tokens_in_today"] == 1500
    assert summary["tokens_out_today"] == 300
    assert summary["cost_today_usd_estimate"] == pytest.approx(0.40)
    assert summary["cost_per_application_usd_estimate"] == pytest.approx(0.40 / 3, abs=1e-4)
    assert summary["usage_reported"] is True
    assert summary["remaining_today"] == 15 - 3


@pytest.mark.unit
def test_today_summary_ignores_runs_from_other_days():
    storage = InMemoryStorage()
    cid = _make_campaign(storage, target=15)
    campaign = storage.campaigns.get(cid)
    now = datetime.now(UTC)
    yesterday = now - timedelta(days=1)
    _add_run(
        storage, cid, timestamp=yesterday,
        stats={"pipelines_started": 5, "cost_usd_estimate": 9.0, "llm_calls": 5},
    )
    svc = CostService(storage)
    summary = svc.today_summary(campaign, now)
    assert summary["applications_today"] == 0
    assert summary["cost_today_usd_estimate"] == 0.0


@pytest.mark.unit
def test_remaining_today_never_goes_negative():
    storage = InMemoryStorage()
    cid = _make_campaign(storage, target=1)
    campaign = storage.campaigns.get(cid)
    now = datetime.now(UTC)
    _add_run(storage, cid, timestamp=now, stats={"pipelines_started": 5})
    svc = CostService(storage)
    summary = svc.today_summary(campaign, now)
    assert summary["remaining_today"] == 0


@pytest.mark.unit
def test_monthly_projection_extrapolates_month_to_date():
    storage = InMemoryStorage()
    cid = _make_campaign(storage, target=15)
    campaign = storage.campaigns.get(cid)
    now = datetime(2026, 7, 10, 12, tzinfo=UTC)
    _add_run(
        storage, cid, timestamp=datetime(2026, 7, 5, tzinfo=UTC),
        stats={"cost_usd_estimate": 10.0, "llm_calls": 4},
    )
    _add_run(
        storage, cid, timestamp=datetime(2026, 7, 9, tzinfo=UTC),
        stats={"cost_usd_estimate": 10.0, "llm_calls": 4},
    )
    svc = CostService(storage)
    projection = svc.monthly_projection(campaign, now)
    assert projection["month_to_date_usd_estimate"] == pytest.approx(20.0)
    # 20.0 spent over 10 days of a 31-day month -> ~62.0 projected.
    assert projection["projected_month_usd_estimate"] == pytest.approx(20.0 / 10 * 31, abs=0.01)
    assert projection["usage_reported"] is True


@pytest.mark.unit
def test_monthly_projection_excludes_prior_months():
    storage = InMemoryStorage()
    cid = _make_campaign(storage, target=15)
    campaign = storage.campaigns.get(cid)
    now = datetime(2026, 7, 10, tzinfo=UTC)
    _add_run(
        storage, cid, timestamp=datetime(2026, 6, 30, tzinfo=UTC),
        stats={"cost_usd_estimate": 999.0, "llm_calls": 1},
    )
    svc = CostService(storage)
    projection = svc.monthly_projection(campaign, now)
    assert projection["month_to_date_usd_estimate"] == 0.0
    assert projection["usage_reported"] is False
