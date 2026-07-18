"""Tests for applicant.evaluation.planner_harness."""

from applicant.evaluation.planner_harness import (
    TaskResult,
    SuiteReport,
    GateResult,
    run_suite,
    ab_gate,
)


class TestTaskResult:
    def test_create_with_minimal_fields(self):
        result = TaskResult(task_id="t1", success=True)
        assert result.task_id == "t1"
        assert result.success is True
        assert result.steps == 0
        assert result.cost == 0.0

    def test_create_with_all_fields(self):
        result = TaskResult(task_id="t2", success=False, steps=5, cost=1.25)
        assert result.task_id == "t2"
        assert result.success is False
        assert result.steps == 5
        assert result.cost == 1.25


class TestSuiteReport:
    def test_all_pass(self):
        results = (TaskResult("a", True), TaskResult("b", True))
        report = SuiteReport(success_rate=1.0, avg_steps=0.0, total_cost=0.0, n_tasks=2, results=results)
        assert report.success_rate == 1.0
        assert report.n_tasks == 2

    def test_all_fail(self):
        results = (TaskResult("a", False), TaskResult("b", False))
        report = SuiteReport(success_rate=0.0, avg_steps=0.0, total_cost=0.0, n_tasks=2, results=results)
        assert report.success_rate == 0.0
        assert report.n_tasks == 2

    def test_half_pass(self):
        results = (TaskResult("a", True), TaskResult("b", False))
        report = SuiteReport(success_rate=0.5, avg_steps=0.0, total_cost=0.0, n_tasks=2, results=results)
        assert report.success_rate == 0.5


class TestRunSuite:
    def test_one_passing_one_failing(self):
        def passing_task(_planner):
            return TaskResult(task_id="pass", success=True, steps=3, cost=0.5)

        def failing_task(_planner):
            return TaskResult(task_id="fail", success=False, steps=1, cost=0.1)

        report = run_suite(object(), [passing_task, failing_task])
        assert report.n_tasks == 2
        assert report.success_rate == 0.5
        assert report.avg_steps == 2.0
        assert report.total_cost == 0.6

    def test_crashing_task(self):
        def crash_task(_planner):
            raise ValueError("boom")
        crash_task.__name__ = "crash_task"

        report = run_suite(object(), [crash_task])
        assert report.n_tasks == 1
        assert report.success_rate == 0.0
        assert report.results[0].task_id == "crash_task"
        assert report.results[0].success is False

    def test_empty_task_list(self):
        report = run_suite(object(), [])
        assert report.success_rate == 0.0
        assert report.avg_steps == 0.0
        assert report.total_cost == 0.0
        assert report.n_tasks == 0
        assert report.results == ()


class TestAbGate:
    def test_pass_candidate_better(self):
        baseline = SuiteReport(success_rate=0.8, avg_steps=5, total_cost=10, n_tasks=10)
        candidate = SuiteReport(success_rate=0.9, avg_steps=4, total_cost=8, n_tasks=10)
        result = ab_gate(baseline, candidate)
        assert result.passed is True
        assert result.baseline_success_rate == 0.8
        assert result.candidate_success_rate == 0.9

    def test_pass_candidate_equal(self):
        baseline = SuiteReport(success_rate=0.8, avg_steps=5, total_cost=10, n_tasks=10)
        candidate = SuiteReport(success_rate=0.8, avg_steps=5, total_cost=10, n_tasks=10)
        result = ab_gate(baseline, candidate)
        assert result.passed is True

    def test_fail_candidate_worse(self):
        baseline = SuiteReport(success_rate=0.8, avg_steps=5, total_cost=10, n_tasks=10)
        candidate = SuiteReport(success_rate=0.6, avg_steps=6, total_cost=12, n_tasks=10)
        result = ab_gate(baseline, candidate)
        assert result.passed is False
        assert "regressed" in result.reason

    def test_pass_with_tolerance(self):
        baseline = SuiteReport(success_rate=0.8, avg_steps=5, total_cost=10, n_tasks=10)
        candidate = SuiteReport(success_rate=0.7, avg_steps=5, total_cost=10, n_tasks=10)
        result = ab_gate(baseline, candidate, tolerance=0.15)
        assert result.passed is True

    def test_fail_beyond_tolerance(self):
        baseline = SuiteReport(success_rate=0.8, avg_steps=5, total_cost=10, n_tasks=10)
        candidate = SuiteReport(success_rate=0.5, avg_steps=5, total_cost=10, n_tasks=10)
        result = ab_gate(baseline, candidate, tolerance=0.15)
        assert result.passed is False

    def test_gate_result_fields(self):
        baseline = SuiteReport(success_rate=0.5, avg_steps=3, total_cost=5, n_tasks=5)
        candidate = SuiteReport(success_rate=0.6, avg_steps=3, total_cost=5, n_tasks=5)
        result = ab_gate(baseline, candidate)
        assert isinstance(result, GateResult)
        assert result.baseline_success_rate == 0.5
        assert result.candidate_success_rate == 0.6
        assert result.reason == "no success-rate regression"
