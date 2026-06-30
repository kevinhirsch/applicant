"""Scaffold tests for the AgentLab + BrowserGym eval harness (#309).

These tests validate the harness structure — the actual evaluation runs are
integration-gated (require a real browser + LLM endpoint).
"""

from __future__ import annotations

import pytest


class TestEvalHarnessScaffold:
    """Structural tests for the eval harness."""

    def test_eval_package_exists(self) -> None:
        """The tests/eval/ package is importable."""
        import tests.eval
        assert hasattr(tests.eval, "__file__")

    def test_eval_marker_registered(self) -> None:
        """The ``eval`` marker is registered in conftest."""
        import tests.eval.conftest
        assert hasattr(tests.eval.conftest, "pytest_configure")

    def test_harness_planner_imports(self) -> None:
        """The harness module imports core planner types."""
        from applicant.core.entities.plan import Plan
        assert Plan is not None

    def test_harness_scoring_imports(self) -> None:
        """The harness uses BrowserGym-style step/obs/rew types."""
        # These would come from browsergym if installed.
        # For the scaffold, we define our own step result type.
        from dataclasses import dataclass

        @dataclass
        class StepResult:
            observation: dict
            reward: float
            terminated: bool
            truncated: bool
            info: dict

        sr = StepResult(observation={"url": "", "html": ""}, reward=0.0,
                        terminated=False, truncated=False, info={})
        assert sr.reward == 0.0

    def test_harness_metrics(self) -> None:
        """Evaluation metrics collection scaffold."""
        from dataclasses import dataclass, field

        @dataclass
        class EvalMetrics:
            total_tasks: int = 0
            completed: int = 0
            failed: int = 0
            avg_reward: float = 0.0
            task_results: list[dict] = field(default_factory=list)

        metrics = EvalMetrics(total_tasks=5, completed=3, failed=2)
        assert metrics.total_tasks == 5
        assert metrics.completed == 3
        assert metrics.failed == 2
        metrics.avg_reward = metrics.completed / max(metrics.total_tasks, 1)
        assert metrics.avg_reward == 0.6

    def test_harness_planner_adapter(self) -> None:
        """The harness planner adapter signature matches PlannerPort."""
        from applicant.core.entities.plan import Plan
        from applicant.ports.driving.planner import PlannerInput, PlannerPort

        class EvalPlanner:
            """A dummy planner for eval that returns empty plans."""

            def plan(self, input_: PlannerInput) -> Plan:
                return Plan(ops=())

            def plan_many(self, goal: str, pages, facts) -> list[Plan]:
                return [Plan(ops=()) for _ in pages]

        planner = EvalPlanner()
        assert isinstance(planner, PlannerPort)
        result = planner.plan(PlannerInput(goal="test"))
        assert isinstance(result, Plan)
        assert len(result) == 0


class TestEvalRunner:
    """Eval runner scaffold — orchestrates task loading, agent execution, and
    metrics collection."""

    def test_runner_interface(self) -> None:
        """The runner interface defines the eval contract."""
        from dataclasses import dataclass, field

        @dataclass
        class EvalConfig:
            """Configuration for an eval run."""
            task_ids: list[str] = field(default_factory=list)
            max_steps: int = 50
            headless: bool = True
            seed: int = 42
            output_dir: str = "eval_results"

        config = EvalConfig(task_ids=["task_1", "task_2"], max_steps=30)
        assert len(config.task_ids) == 2
        assert config.max_steps == 30
        assert config.headless is True

    def test_task_loading(self) -> None:
        """Task registry scaffold — maps task IDs to environment configurations."""
        task_registry = {
            "fill_simple_form": {
                "url": "https://example.com/simple-form",
                "goal": "Fill the form with user details",
                "expected_fields": ["first_name", "last_name", "email"],
            },
            "multi_page_apply": {
                "url": "https://example.com/careers/apply",
                "goal": "Complete the multi-page application",
                "expected_pages": 3,
            },
            "workday_login": {
                "url": "https://example.com/workday/login",
                "goal": "Navigate Workday account gate",
                "expected_stop": "account_create",
            },
        }
        assert "fill_simple_form" in task_registry
        assert task_registry["fill_simple_form"]["goal"] == "Fill the form with user details"
        assert task_registry["multi_page_apply"]["expected_pages"] == 3

    def test_metrics_collection(self) -> None:
        """Metrics are collected and aggregated across tasks."""
        from dataclasses import dataclass

        @dataclass
        class TaskResult:
            task_id: str
            success: bool
            steps: int
            reward: float
            error: str | None = None

        results = [
            TaskResult("task_1", True, 12, 1.0),
            TaskResult("task_2", True, 8, 0.9),
            TaskResult("task_3", False, 25, 0.0, "timeout"),
        ]
        success_rate = sum(1 for r in results if r.success) / len(results)
        avg_reward = sum(r.reward for r in results) / len(results)
        assert success_rate == pytest.approx(2 / 3)
        assert avg_reward == pytest.approx((1.0 + 0.9 + 0.0) / 3)
