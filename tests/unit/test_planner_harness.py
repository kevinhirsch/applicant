"""Tests for applicant.evaluation.planner_harness."""

import pytest
from applicant.evaluation.planner_harness import (
    TaskResult,
    SuiteReport,
    GateResult,
    run_suite,
    ab_gate,
)


@pytest.fixture(autouse=True)
def _no_cache():
    pass


class TestTaskResult:
    """Construction and immutability of TaskResult."""

    @pytest.mark.unit
    def test_create_with_minimal_fields(self):
        result = TaskResult(task_id="t1", success=True)
        assert result.task_id == "t1"
        assert result.success is True
        assert result.steps == 0
        assert result.cost == 0.0

    @pytest.mark.unit
    def test_create_with_all_fields(self):
        result = TaskResult(task_id="t2", success=False, steps=5, cost=1.25)
        assert result.task_id == "t2"
        assert result.success is False
        assert result.steps == 5
        assert result.cost == 1.25

    @pytest.mark.unit
    def test_frozen_prevents_mutation(self):
        result = TaskResult(task_id="t3", success=True)
        with pytest.raises(AttributeError):
            result.success = False


class TestSuiteReport:
    """Construction and defaults of SuiteReport."""

    @pytest.mark.unit
    def test_create_with_default_results(self):
        report = SuiteReport(success_rate=0.8, avg_steps=5.0, total_cost=10.0, n_tasks=10)
        assert report.success_rate == 0.8
        assert report.avg_steps == 5.0
        assert report.total_cost == 10.0
        assert report.n_tasks == 10
        assert report.results == ()

    @pytest.mark.unit
    def test_create_with_results(self):
        results = (TaskResult("a", True), TaskResult("b", False))
        report = SuiteReport(
            success_rate=0.5, avg_steps=3.0, total_cost=6.0, n_tasks=2, results=results
        )
        assert report.results == results


class TestRunSuite:
    """run_suite aggregation logic for empty, passing, failing, and mixed tasks."""

    @pytest.mark.unit
    def test_empty_tasks_returns_zeroed_report(self):
        report = run_suite(object(), [])
        assert report.success_rate == 0.0
        assert report.avg_steps == 0.0
        assert report.total_cost == 0.0
        assert report.n_tasks == 0

    @pytest.mark.unit
    def test_one_success_task(self):
        def success_task(planner):
            return TaskResult(task_id="s1", success=True, steps=3, cost=1.5)

        report = run_suite(object(), [success_task])
        assert report.success_rate == 1.0
        assert report.avg_steps == 3.0
        assert report.total_cost == 1.5
        assert report.n_tasks == 1

    @pytest.mark.unit
    def test_task_raises_exception_yields_failure(self):
        def failing_task(planner):
            raise ValueError("task failed")

        report = run_suite(object(), [failing_task])
        assert report.success_rate == 0.0
        assert report.n_tasks == 1
        assert report.total_cost == 0.0

    @pytest.mark.unit
    def test_mixed_tasks_correct_aggregation(self):
        def pass_task(planner):
            return TaskResult(task_id="pass", success=True, steps=4, cost=2.0)

        def fail_task(planner):
            return TaskResult(task_id="fail", success=False, steps=1, cost=0.5)

        def crash_task(planner):
            raise RuntimeError("crash")

        report = run_suite(object(), [pass_task, fail_task, crash_task])
        assert report.n_tasks == 3
        assert report.success_rate == pytest.approx(1.0 / 3.0)
        assert report.avg_steps == pytest.approx((4 + 1 + 0) / 3.0)
        assert report.total_cost == pytest.approx(2.0 + 0.5)
        assert len(report.results) == 3
        # crashed task gets task_id from __name__ and success=False
        assert report.results[0].task_id == "pass"
        assert report.results[1].task_id == "fail"
        assert report.results[2].task_id == "crash_task"


class TestGateResult:
    """Construction of GateResult."""

    @pytest.mark.unit
    def test_create_with_minimal_fields(self):
        result = GateResult(passed=True, baseline_success_rate=0.8, candidate_success_rate=0.9)
        assert result.passed is True
        assert result.baseline_success_rate == 0.8
        assert result.candidate_success_rate == 0.9
        assert result.reason == ""

    @pytest.mark.unit
    def test_create_with_reason(self):
        result = GateResult(
            passed=False,
            baseline_success_rate=0.8,
            candidate_success_rate=0.6,
            reason="regressed",
        )
        assert result.passed is False
        assert result.reason == "regressed"


class TestAbGate:
    """A/B gating logic: equal, better, worse, and tolerance cases."""

    @pytest.mark.unit
    def test_equal_baselines_passes(self):
        base = SuiteReport(success_rate=0.8, avg_steps=5, total_cost=10, n_tasks=10)
        cand = SuiteReport(success_rate=0.8, avg_steps=5, total_cost=10, n_tasks=10)
        result = ab_gate(base, cand)
        assert result.passed is True
        assert result.reason == "no success-rate regression"

    @pytest.mark.unit
    def test_baseline_better_still_passes(self):
        base = SuiteReport(success_rate=0.8, avg_steps=5, total_cost=10, n_tasks=10)
        cand = SuiteReport(success_rate=0.85, avg_steps=4, total_cost=8, n_tasks=10)
        result = ab_gate(base, cand)
        assert result.passed is True

    @pytest.mark.unit
    def test_candidate_worse_fails_with_reason(self):
        base = SuiteReport(success_rate=0.8, avg_steps=5, total_cost=10, n_tasks=10)
        cand = SuiteReport(success_rate=0.6, avg_steps=6, total_cost=12, n_tasks=10)
        result = ab_gate(base, cand)
        assert result.passed is False
        assert "regressed" in result.reason
        assert result.baseline_success_rate == 0.8
        assert result.candidate_success_rate == 0.6

    @pytest.mark.unit
    def test_tolerance_absorbs_small_regression(self):
        base = SuiteReport(success_rate=0.8, avg_steps=5, total_cost=10, n_tasks=10)
        cand = SuiteReport(success_rate=0.75, avg_steps=5, total_cost=10, n_tasks=10)
        result = ab_gate(base, cand, tolerance=0.1)
        assert result.passed is True

    @pytest.mark.unit
    def test_tolerance_exceeded_fails(self):
        base = SuiteReport(success_rate=0.8, avg_steps=5, total_cost=10, n_tasks=10)
        cand = SuiteReport(success_rate=0.65, avg_steps=5, total_cost=10, n_tasks=10)
        result = ab_gate(base, cand, tolerance=0.1)
        assert result.passed is False
