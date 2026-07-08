"""Unit tests for the pure cost-estimate core rule (P1-6 cost & pace guardrails)."""

from __future__ import annotations

import pytest

from applicant.core.rules.cost_estimate import (
    average_cost_per_application,
    days_in_month,
    estimate_cost_usd,
    project_monthly_usd,
)


@pytest.mark.unit
def test_estimate_cost_usd_uses_the_configured_rates():
    cost = estimate_cost_usd(1000, 1000, input_price_per_1k=0.10, output_price_per_1k=0.20)
    assert cost == pytest.approx(0.30)


@pytest.mark.unit
def test_estimate_cost_usd_defaults_are_positive_and_deterministic():
    cost = estimate_cost_usd(2000, 500)
    assert cost > 0
    assert cost == estimate_cost_usd(2000, 500)


@pytest.mark.unit
def test_estimate_cost_usd_clamps_negative_tokens_to_zero():
    """A defensively-parsed provider body must never yield a negative "spend"."""
    assert estimate_cost_usd(-100, -100) == 0.0


@pytest.mark.unit
def test_days_in_month_handles_december_year_rollover():
    assert days_in_month(2026, 1) == 31
    assert days_in_month(2026, 2) == 28  # 2026 is not a leap year
    assert days_in_month(2024, 2) == 29  # 2024 is a leap year
    assert days_in_month(2026, 12) == 31


@pytest.mark.unit
def test_project_monthly_usd_linear_extrapolation():
    # $30 spent over 10 days of a 30-day month -> $90 projected for the month.
    assert project_monthly_usd(30.0, 10, 30) == pytest.approx(90.0)


@pytest.mark.unit
def test_project_monthly_usd_first_day_returns_month_to_date_not_a_division_blowup():
    assert project_monthly_usd(5.0, 1, 30) == 5.0
    assert project_monthly_usd(5.0, 0, 30) == 5.0


@pytest.mark.unit
def test_average_cost_per_application_none_when_nothing_to_divide_by():
    assert average_cost_per_application(12.0, 0) is None
    assert average_cost_per_application(12.0, -1) is None


@pytest.mark.unit
def test_average_cost_per_application_divides_evenly():
    assert average_cost_per_application(12.0, 4) == pytest.approx(3.0)
