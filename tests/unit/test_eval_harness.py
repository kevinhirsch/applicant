"""Unit tests for the browser-agent eval harness (Issue #309).

Tests cover:
- Suite execution and metric reporting
- A/B gating with regression detection
- Material quality judging (LLM-as-judge)
"""

from __future__ import annotations

from applicant.evaluation import (
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
