"""Unit tests for the observability metrics surface (FR-OBS-2 / NFR-OPS, #362).

A small, dependency-free, in-process metrics registry: tick counters, a scheduler-
liveness heartbeat, and an idempotent consecutive-failure operator-alert decision.
Deterministic with an injected clock.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from applicant.observability import metrics as m


@pytest.mark.unit
def test_record_tick_counts_and_heartbeat():
    reg = m.Metrics()
    t0 = datetime(2026, 6, 16, 9, 0, tzinfo=UTC)
    reg.record_tick(success=True, now=t0)
    snap = reg.snapshot()
    assert snap["ticks_total"] == 1
    assert snap["ticks_succeeded"] == 1
    assert snap["ticks_failed"] == 0
    assert snap["last_heartbeat"] == t0.isoformat()
    assert snap["last_tick_success"] is True
    assert snap["consecutive_failures"] == 0


@pytest.mark.unit
def test_extra_counters_accumulate():
    reg = m.Metrics()
    reg.record_tick(success=True, campaigns=2, ladder_fired=1)
    reg.record_tick(success=True, campaigns=3, ladder_fired=0)
    snap = reg.snapshot()
    assert snap["campaigns"] == 5
    assert snap["ladder_fired"] == 1


@pytest.mark.unit
def test_consecutive_failures_grow_and_reset_on_success():
    reg = m.Metrics(failure_alert_threshold=3)
    reg.record_tick(success=False)
    reg.record_tick(success=False)
    assert reg.snapshot()["consecutive_failures"] == 2
    reg.record_tick(success=True)
    assert reg.snapshot()["consecutive_failures"] == 0


@pytest.mark.unit
def test_alert_fires_once_at_threshold_then_latches():
    reg = m.Metrics(failure_alert_threshold=3)
    reg.record_tick(success=False)
    reg.record_tick(success=False)
    assert reg.consecutive_failure_alert() is None  # below threshold
    reg.record_tick(success=False)  # 3rd consecutive failure
    alert = reg.consecutive_failure_alert()
    assert alert is not None
    assert alert["consecutive_failures"] == 3
    assert alert["threshold"] == 3
    # Idempotent: the same stall does not re-alert.
    reg.record_tick(success=False)
    assert reg.consecutive_failure_alert() is None


@pytest.mark.unit
def test_alert_rearms_after_a_successful_tick():
    reg = m.Metrics(failure_alert_threshold=2)
    reg.record_tick(success=False)
    reg.record_tick(success=False)
    assert reg.consecutive_failure_alert() is not None
    reg.record_tick(success=True)  # re-arm
    reg.record_tick(success=False)
    reg.record_tick(success=False)
    assert reg.consecutive_failure_alert() is not None


@pytest.mark.unit
def test_threshold_clamped_to_at_least_one():
    reg = m.Metrics(failure_alert_threshold=0)
    assert reg.failure_alert_threshold == 1
    reg.record_tick(success=False)
    assert reg.consecutive_failure_alert() is not None


@pytest.mark.unit
def test_module_singleton_functions_and_reset():
    m.reset()
    try:
        m.record_tick(success=True, now=datetime(2026, 6, 16, 9, 0, tzinfo=UTC))
        assert m.snapshot()["ticks_total"] == 1
    finally:
        m.reset()
    assert m.snapshot()["ticks_total"] == 0


@pytest.mark.unit
def test_heartbeat_advances_with_clock():
    reg = m.Metrics()
    t0 = datetime(2026, 6, 16, 9, 0, tzinfo=UTC)
    reg.record_tick(success=True, now=t0)
    t1 = t0 + timedelta(minutes=5)
    reg.record_tick(success=True, now=t1)
    assert reg.snapshot()["last_heartbeat"] == t1.isoformat()
