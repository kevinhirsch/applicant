"""Unit tests for UsageLedger (P1-6 cost & pace guardrails).

The ledger is the process-lived accumulator the shared LLM adapter singleton
feeds; AgentLoop drains it into durable ``agent_runs.stats`` each tick. These
tests exercise it in isolation (record/drain/peek semantics) — see
``test_agent_loop_usage_and_budget.py`` for the drain-into-a-tick integration.
"""

from __future__ import annotations

from datetime import date

import pytest

from applicant.application.services.usage_ledger import UsageLedger


@pytest.mark.unit
def test_record_accumulates_across_multiple_calls():
    ledger = UsageLedger()
    day = date(2026, 7, 7)
    ledger.record(day, tokens_in=100, tokens_out=50, cost_usd=0.10)
    ledger.record(day, tokens_in=200, tokens_out=25, cost_usd=0.05)
    snapshot = ledger.peek(day)
    assert snapshot == {"tokens_in": 300, "tokens_out": 75, "cost_usd": pytest.approx(0.15), "calls": 2}


@pytest.mark.unit
def test_peek_does_not_clear_the_ledger():
    ledger = UsageLedger()
    day = date(2026, 7, 7)
    ledger.record(day, tokens_in=10, tokens_out=10, cost_usd=0.01)
    ledger.peek(day)
    ledger.peek(day)
    assert ledger.peek(day)["calls"] == 1


@pytest.mark.unit
def test_drain_pops_and_zeroes():
    ledger = UsageLedger()
    day = date(2026, 7, 7)
    ledger.record(day, tokens_in=10, tokens_out=5, cost_usd=0.02)
    drained = ledger.drain(day)
    assert drained["calls"] == 1
    # A second drain (nothing recorded since) returns the zero row.
    assert ledger.drain(day) == {"tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "calls": 0}


@pytest.mark.unit
def test_days_are_independent():
    ledger = UsageLedger()
    d1, d2 = date(2026, 7, 7), date(2026, 7, 8)
    ledger.record(d1, tokens_in=100, tokens_out=0, cost_usd=1.0)
    ledger.record(d2, tokens_in=5, tokens_out=0, cost_usd=0.01)
    assert ledger.peek(d1)["tokens_in"] == 100
    assert ledger.peek(d2)["tokens_in"] == 5


@pytest.mark.unit
def test_recording_a_new_day_does_not_wipe_an_undrained_older_day():
    """Regression: usage for a day that has not been drained yet must survive a
    later day's first ``record`` call — losing it would be silent data loss."""
    ledger = UsageLedger()
    yesterday, today = date(2026, 7, 7), date(2026, 7, 8)
    ledger.record(yesterday, tokens_in=50, tokens_out=10, cost_usd=0.5)
    # Nobody drained "yesterday" before "today" starts recording.
    ledger.record(today, tokens_in=1, tokens_out=1, cost_usd=0.001)
    assert ledger.peek(yesterday)["tokens_in"] == 50
    assert ledger.peek(today)["tokens_in"] == 1
