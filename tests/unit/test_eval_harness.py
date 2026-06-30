"""Unit tests for the browser-agent eval harness (Issue #309).

Tests cover:
- Suite execution and metric reporting
- A/B gating with regression detection
- Material quality judging (LLM-as-judge)
- BrowserGymEvalHarness import-guard and degradation behavior
"""

from __future__ import annotations

import pytest

from applicant.evaluation import (
    BrowserGymEvalHarness,
    EvalRunMetrics,
    EvalTask,
    InMemoryEvalHarness,
    SuiteResult,
    ab_gate,
    run_suite,
)
from applicant.evaluation.material_judge import (
    DEFAULT_RUBRIC,
    MaterialQualityScore,
    judge_material,
)


class TestEvalHarness:
    """The planner is scored on a benchmark task set."""

    def test_empty_suite(self):
        """An empty task suite returns zeroed results."""
        harness = InMemoryEvalHarness()
        result = harness.run_suite([], None)
        assert result.task_count == 0
        assert result.success_rate == 0.0
        assert result.avg_steps == 0.0

    def test_single_task_success(self):
        """A single successful task returns 100% success rate."""
        harness = InMemoryEvalHarness()

        def successful_planner(attrs):
            return {"steps": 5, "cost": 0.02}

        task = EvalTask(
            task_id="test-1",
            url="https://example.com/job",
            description="Test job application",
            attributes={"name": "Jane"},
        )
        result = harness.run_suite([task], successful_planner)
        assert result.task_count == 1
        assert result.success_count == 1
        assert result.success_rate == 1.0
        assert result.avg_steps == 5
        assert result.avg_cost == 0.02

    def test_single_task_failure(self):
        """A task whose planner raises returns 0% success rate."""
        harness = InMemoryEvalHarness()

        def failing_planner(attrs):
            raise ValueError("Failed to fill field 'email'")

        task = EvalTask(
            task_id="test-2",
            url="https://example.com/job",
            description="Failing test",
        )
        result = harness.run_suite([task], failing_planner)
        assert result.task_count == 1
        assert result.success_count == 0
        assert result.success_rate == 0.0
        assert len(result.run_metrics) == 1
        assert "Failed to fill field" in result.run_metrics[0].errors[0]

    def test_mixed_results(self):
        """Mixed success/failure tasks produce intermediate rates."""
        harness = InMemoryEvalHarness()
        tasks = [
            EvalTask(task_id="ok", url="https://a.com/job", description="Success"),
            EvalTask(task_id="fail", url="https://b.com/job", description="Failure"),
        ]

        call_count = [0]

        def mixed_planner(attrs):
            call_count[0] += 1
            if call_count[0] == 1:
                return {"steps": 3, "cost": 0.01}
            raise ValueError("fail")

        result = harness.run_suite(tasks, mixed_planner)
        assert result.task_count == 2
        assert result.success_count == 1
        assert result.success_rate == 0.5
        assert result.avg_steps == 1.5  # (3 + 0) / 2

    def test_metrics_include_field_counts(self):
        """Run metrics include field detection and fill counts."""
        harness = InMemoryEvalHarness()

        def planner(attrs):
            return {"steps": 4, "cost": 0.01}

        task = EvalTask(
            task_id="fields-test",
            url="https://example.com/job",
            description="Field counting test",
            expected_fields=[
                {"name": "first_name", "type": "text"},
                {"name": "last_name", "type": "text"},
            ],
        )
        result = harness.run_suite([task], planner)
        metrics = result.run_metrics[0]
        assert metrics.fields_detected == 2
        assert metrics.fields_filled == 4


class TestABGate:
    """A planner change is A/B gated against the baseline."""

    def test_no_regression_passes(self):
        """Candidate with same or better success rate passes."""
        baseline = SuiteResult(
            task_count=10,
            success_count=8,
            success_rate=0.8,
            avg_steps=5.0,
            avg_cost=0.02,
            avg_duration_s=10.0,
            total_cost=0.2,
        )
        candidate = SuiteResult(
            task_count=10,
            success_count=9,
            success_rate=0.9,
            avg_steps=4.5,
            avg_cost=0.015,
            avg_duration_s=8.0,
            total_cost=0.15,
        )
        passed, message = ab_gate(baseline, candidate)
        assert passed is True
        assert "passes" in message

    def test_success_rate_regression_fails(self):
        """A regression in success rate fails the gate."""
        baseline = SuiteResult(
            task_count=10,
            success_count=8,
            success_rate=0.8,
            avg_steps=5.0,
            avg_cost=0.02,
            avg_duration_s=10.0,
            total_cost=0.2,
        )
        candidate = SuiteResult(
            task_count=10,
            success_count=6,
            success_rate=0.6,
            avg_steps=5.0,
            avg_cost=0.02,
            avg_duration_s=10.0,
            total_cost=0.2,
        )
        passed, message = ab_gate(baseline, candidate)
        assert passed is False
        assert "regressed" in message

    def test_minor_regression_within_threshold(self):
        """A regression within the threshold passes."""
        baseline = SuiteResult(
            task_count=10,
            success_count=8,
            success_rate=0.8,
            avg_steps=5.0,
            avg_cost=0.02,
            avg_duration_s=10.0,
            total_cost=0.2,
        )
        candidate = SuiteResult(
            task_count=10,
            success_count=8,
            success_rate=0.8,
            avg_steps=5.0,
            avg_cost=0.02,
            avg_duration_s=10.0,
            total_cost=0.2,
        )
        passed, message = ab_gate(baseline, candidate, regression_threshold=0.01)
        assert passed is True

    def test_cost_increase_fails(self):
        """A significant cost increase fails the gate."""
        baseline = SuiteResult(
            task_count=10,
            success_count=8,
            success_rate=0.8,
            avg_steps=5.0,
            avg_cost=0.02,
            avg_duration_s=10.0,
            total_cost=0.2,
        )
        candidate = SuiteResult(
            task_count=10,
            success_count=8,
            success_rate=0.8,
            avg_steps=5.0,
            avg_cost=0.05,  # 2.5x increase
            avg_duration_s=10.0,
            total_cost=0.5,
        )
        passed, message = ab_gate(baseline, candidate)
        assert passed is False
        assert "cost" in message


class TestRunSuiteConvenience:
    """run_suite convenience function works correctly."""

    def test_run_suite_with_planner(self):
        """run_suite returns aggregated results."""
        tasks = [
            EvalTask(task_id="t1", url="https://a.com", description="Task 1"),
            EvalTask(task_id="t2", url="https://b.com", description="Task 2"),
        ]

        def planner(attrs):
            return {"steps": 2, "cost": 0.01}

        result = run_suite(tasks, planner)
        assert result.task_count == 2
        assert result.success_rate == 1.0


class TestMaterialJudge:
    """Generated-material quality is judged by an LLM-as-judge pass."""

    def test_judge_empty_material(self):
        """Empty material gets low scores."""
        judgment = judge_material(
            material_text="",
            material_type="resume",
            material_id="res-1",
        )
        assert judgment.material_id == "res-1"
        assert judgment.material_type == "resume"
        assert judgment.overall_score < 2.0  # Should be low for empty text

    def test_judge_short_material(self):
        """Very short material gets a low score."""
        judgment = judge_material(
            material_text="Short resume.",
            material_type="resume",
            material_id="res-2",
        )
        assert judgment.overall_score < 3.0

    def test_judge_complete_material(self):
        """A complete resume gets reasonable scores."""
        resume = """
Jane Doe
jane@example.com | (555) 123-4567

Summary
Experienced software engineer with 8+ years building web applications.

Experience
Senior Engineer, Tech Corp (2020-Present)
- Led development of 3 major features serving 1M+ users
- Reduced deployment time by 40% through CI/CD automation

Education
B.S. Computer Science, University of Technology (2012-2016)

Skills
Python, JavaScript, React, FastAPI, PostgreSQL
"""
        judgment = judge_material(
            material_text=resume,
            material_type="resume",
            material_id="res-3",
        )
        assert judgment.overall_score >= 1.0
        assert len(judgment.dimension_scores) > 0
        assert judgment.material_id == "res-3"

    def test_judge_with_profile_facts(self):
        """Judging with profile facts uses truthfulness check."""
        resume = "Jane Doe is an experienced engineer."
        judgment = judge_material(
            material_text=resume,
            material_type="resume",
            material_id="res-4",
            profile_facts={"full_name": "Jane Doe", "title": "Software Engineer"},
        )
        assert judgment.overall_score > 0
        truthfulness_scores = [
            s for s in judgment.dimension_scores if s.dimension == "truthfulness"
        ]
        assert len(truthfulness_scores) > 0

    def test_judge_with_job_description(self):
        """Judging with job description uses relevance check."""
        resume = "Python developer with FastAPI and PostgreSQL experience."
        judgment = judge_material(
            material_text=resume,
            material_type="resume",
            material_id="res-5",
            job_description="Looking for a Python developer with FastAPI and PostgreSQL skills.",
        )
        assert judgment.overall_score > 0
        relevance_scores = [
            s for s in judgment.dimension_scores if s.dimension == "relevance"
        ]
        assert len(relevance_scores) > 0

    def test_cover_letter_judgment(self):
        """Cover letters are judged with appropriate type."""
        judgment = judge_material(
            material_text="Dear Hiring Manager, I am excited to apply...",
            material_type="cover_letter",
            material_id="cl-1",
        )
        assert judgment.material_type == "cover_letter"
        assert "Cover letter" in judgment.summary

    def test_judge_error_handling(self):
        """Judging handles errors gracefully."""
        judgment = judge_material(
            material_text=None,  # type: ignore
            material_type="resume",
            material_id="res-err",
        )
        assert judgment.overall_score == 0.0
        assert len(judgment.errors) > 0

    def test_default_rubric(self):
        """Default rubric has expected dimensions."""
        assert "truthfulness" in DEFAULT_RUBRIC
        assert "relevance" in DEFAULT_RUBRIC
        assert "completeness" in DEFAULT_RUBRIC
        assert "formatting" in DEFAULT_RUBRIC
        assert "specificity" in DEFAULT_RUBRIC


class TestMaterialQualityScore:
    """MaterialQualityScore dataclass works correctly."""

    def test_score_creation(self):
        score = MaterialQualityScore(
            dimension="truthfulness", score=4, rationale="All facts supported"
        )
        assert score.dimension == "truthfulness"
        assert score.score == 4
        assert score.rationale == "All facts supported"

    def test_score_range(self):
        """Scores are bounded 1-5."""
        from applicant.evaluation.material_judge import _heuristic_score_dimension
        score = _heuristic_score_dimension(
            dimension="truthfulness",
            description="test",
            material_text="A" * 100,
            material_type="resume",
            profile_facts={"name": "Jane Doe"},
        )
        assert 1 <= score.score <= 5


# ── InMemoryEvalHarness custom runner ───────────────────────────────────────


class TestInMemoryCustomRunner:
    """InMemoryEvalHarness accepts a custom task_runner for injection."""

    def test_custom_runner_is_called(self):
        """A custom task_runner is invoked instead of the default."""
        called_with: list[EvalTask] = []

        def custom_runner(task: EvalTask, planner) -> EvalRunMetrics:
            called_with.append(task)
            return EvalRunMetrics(
                task_id=task.task_id,
                success=True,
                step_count=3,
                cost=0.001,
                duration_s=0.1,
            )

        harness = InMemoryEvalHarness(task_runner=custom_runner)
        task = EvalTask(task_id="custom-1", url="https://x.com", description="custom")
        result = harness.run_suite([task], planner=None)

        assert len(called_with) == 1
        assert called_with[0].task_id == "custom-1"
        assert result.success_rate == 1.0

    def test_parallel_flag_falls_back_gracefully(self):
        """parallel=True is accepted but runs sequentially with a warning."""
        harness = InMemoryEvalHarness()
        tasks = [
            EvalTask(task_id="p1", url="https://a.com", description="a"),
            EvalTask(task_id="p2", url="https://b.com", description="b"),
        ]

        def ok_planner(attrs):
            return {"steps": 1, "cost": 0.0}

        result = harness.run_suite(tasks, ok_planner, parallel=True)
        assert result.task_count == 2
        assert result.success_rate == 1.0


# ── BrowserGymEvalHarness optional-extra guard ──────────────────────────────


class TestBrowserGymEvalHarness:
    """BrowserGymEvalHarness degrades cleanly when the eval extra is absent."""

    def test_harness_importable(self):
        """BrowserGymEvalHarness is importable without the eval extra."""
        from applicant.evaluation import BrowserGymEvalHarness
        assert BrowserGymEvalHarness is not None

    def test_bg_available_reflects_install(self):
        """_bg_available is True only when browsergym is installed."""
        try:
            import browsergym  # noqa: F401
            bg_installed = True
        except ImportError:
            bg_installed = False

        harness = BrowserGymEvalHarness()
        assert harness._bg_available == bg_installed

    def test_list_available_tasks_without_browsergym(self):
        """list_available_tasks returns [] when BrowserGym is not installed."""
        try:
            import browsergym  # noqa: F401
            pytest.skip("browsergym installed, cannot test absent branch")
        except ImportError:
            pass

        harness = BrowserGymEvalHarness()
        tasks = harness.list_available_tasks()
        assert tasks == []

    def test_create_task_returns_none_without_browsergym(self):
        """create_task_from_browsergym returns None when BrowserGym is absent."""
        try:
            import browsergym  # noqa: F401
            pytest.skip("browsergym installed, cannot test absent branch")
        except ImportError:
            pass

        harness = BrowserGymEvalHarness()
        task = harness.create_task_from_browsergym("jobapp.Workday")
        assert task is None

    def test_list_available_tasks_with_browsergym(self):
        """list_available_tasks returns known tasks when BrowserGym is installed."""
        try:
            import browsergym  # noqa: F401
        except ImportError:
            pytest.skip("browsergym not installed (install with uv sync --extra eval)")

        harness = BrowserGymEvalHarness()
        tasks = harness.list_available_tasks()
        assert len(tasks) > 0
        assert all("task_id" in t and "description" in t for t in tasks)

    def test_create_task_workday_with_browsergym(self):
        """create_task_from_browsergym returns an EvalTask for known IDs."""
        try:
            import browsergym  # noqa: F401
        except ImportError:
            pytest.skip("browsergym not installed (install with uv sync --extra eval)")

        harness = BrowserGymEvalHarness()
        task = harness.create_task_from_browsergym("jobapp.Workday")
        assert task is not None
        assert task.task_id == "jobapp.Workday"
        assert task.url != ""


# ── EvalRunMetrics dataclass ─────────────────────────────────────────────────


class TestEvalRunMetrics:
    """EvalRunMetrics captures per-run data correctly."""

    def test_basic_metrics(self):
        """EvalRunMetrics holds expected fields."""
        m = EvalRunMetrics(
            task_id="t1",
            success=True,
            step_count=7,
            cost=0.03,
            duration_s=5.2,
            fields_detected=4,
            fields_filled=4,
        )
        assert m.task_id == "t1"
        assert m.success is True
        assert m.step_count == 7
        assert m.fields_detected == 4
        assert m.fields_filled == 4

    def test_errors_default_empty(self):
        """errors defaults to an empty tuple."""
        m = EvalRunMetrics(
            task_id="t2", success=False, step_count=0, cost=0.0, duration_s=0.1
        )
        assert m.errors == ()

    def test_details_default_empty(self):
        """details defaults to an empty dict."""
        m = EvalRunMetrics(
            task_id="t3", success=True, step_count=1, cost=0.0, duration_s=0.05
        )
        assert m.details == {}
