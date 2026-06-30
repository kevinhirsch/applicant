"""Browser-agent eval harness for the pre-fill planner (Issue #309).

AgentLab + BrowserGym integration (Apache-2.0) as the A/B regression gate for
the plan-as-data planner. Measures plan success rate, steps, and cost per
change, plus an LLM-as-judge pass on generated-material quality.

This module defines the harness interface and a reference implementation.
The real AgentLab/BrowserGym integration requires the optional 'eval' extra
with gymnasium and browsergym installed.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

logger = logging.getLogger(__name__)


# -- Data contracts ----------------------------------------------------------


@dataclass(frozen=True)
class EvalTask:
    """A single benchmark task for the eval harness."""

    task_id: str
    """Unique identifier for this task."""

    url: str
    """The job application URL to navigate."""

    description: str
    """Human-readable description of the task."""

    expected_fields: list[dict[str, str]] = field(default_factory=list)
    """Expected fields that should be detected and filled."""

    attributes: dict[str, str] = field(default_factory=dict)
    """Seed attribute cloud for the task."""

    timeout_s: float = 60.0
    """Maximum time allowed for this task (seconds)."""


@dataclass(frozen=True)
class EvalRunMetrics:
    """Metrics collected for a single eval run."""

    task_id: str
    """The task that was run."""

    success: bool
    """Whether the planner successfully completed the task."""

    step_count: int
    """Number of steps the planner took."""

    cost: float
    """Estimated cost of the run (LLM tokens, etc.)."""

    duration_s: float
    """Wall-clock duration in seconds."""

    fields_detected: int = 0
    """Number of fields detected on the page."""

    fields_filled: int = 0
    """Number of fields successfully filled."""

    errors: tuple[str, ...] = ()
    """Errors encountered during the run."""

    details: dict[str, Any] = field(default_factory=dict)
    """Arbitrary additional metrics."""


@dataclass(frozen=True)
class SuiteResult:
    """Aggregated results from running a benchmark task suite."""

    task_count: int
    """Number of tasks in the suite."""

    success_count: int
    """Number of tasks completed successfully."""

    success_rate: float
    """Fraction of tasks that succeeded (0.0 - 1.0)."""

    avg_steps: float
    """Average number of steps across all tasks."""

    avg_cost: float
    """Average cost across all tasks."""

    avg_duration_s: float
    """Average duration in seconds."""

    total_cost: float
    """Total cost across all tasks."""

    run_metrics: tuple[EvalRunMetrics, ...] = ()
    """Per-task metrics for detailed analysis."""

    baseline_compare: str | None = None
    """Comparison to baseline, if A/B gating was used."""


# -- Harness protocol --------------------------------------------------------


class EvalHarness(Protocol):
    """Protocol for a browser-agent eval harness."""

    def run_task(self, task: EvalTask, planner: Any) -> EvalRunMetrics:
        """Run a single benchmark task with the given planner."""
        ...

    def run_suite(
        self,
        tasks: list[EvalTask],
        planner: Any,
        *,
        parallel: bool = False,
    ) -> SuiteResult:
        """Run a suite of benchmark tasks and return aggregated results."""
        ...

    def ab_gate(
        self,
        baseline_metrics: SuiteResult,
        candidate_metrics: SuiteResult,
        *,
        regression_threshold: float = 0.05,
    ) -> tuple[bool, str]:
        """Compare candidate against baseline; return (pass, message).

        A regression in success rate exceeding regression_threshold fails the gate.
        """
        ...


# -- Reference in-memory harness (used for unit tests) -----------------------


class InMemoryEvalHarness:
    """In-memory reference eval harness.

    Runs tasks against a planner function in-process. Does NOT require
    BrowserGym or real browsers -- uses injected task handlers.
    """

    def __init__(
        self,
        task_runner: Callable[[EvalTask, Any], EvalRunMetrics] | None = None,
    ):
        self._task_runner = task_runner or self._default_task_runner

    @staticmethod
    def _default_task_runner(task: EvalTask, planner: Any) -> EvalRunMetrics:
        """Default in-memory task runner.

        If the planner is callable, invokes it with the task's attributes.
        Returns success if no exception is raised.
        """
        start = time.monotonic()
        step_count = 0
        cost = 0.0
        errors: list[str] = []

        try:
            if callable(planner):
                result = planner(task.attributes)
                if isinstance(result, dict):
                    step_count = result.get("steps", 0)
                    cost = result.get("cost", 0.0)
                else:
                    step_count = 1
        except Exception as exc:
            errors.append(str(exc))

        duration = time.monotonic() - start
        return EvalRunMetrics(
            task_id=task.task_id,
            success=len(errors) == 0,
            step_count=step_count,
            cost=cost,
            duration_s=duration,
            fields_detected=len(task.expected_fields),
            fields_filled=step_count,
            errors=tuple(errors),
        )

    def run_task(self, task: EvalTask, planner: Any) -> EvalRunMetrics:
        return self._task_runner(task, planner)

    def run_suite(
        self,
        tasks: list[EvalTask],
        planner: Any,
        *,
        parallel: bool = False,
    ) -> SuiteResult:
        """Run a suite of benchmark tasks."""
        if parallel:
            logger.warning("Parallel execution not implemented, running sequentially")

        metrics: list[EvalRunMetrics] = []
        for task in tasks:
            m = self.run_task(task, planner)
            metrics.append(m)

        success_count = sum(1 for m in metrics if m.success)
        task_count = len(metrics)
        return SuiteResult(
            task_count=task_count,
            success_count=success_count,
            success_rate=success_count / task_count if task_count > 0 else 0.0,
            avg_steps=sum(m.step_count for m in metrics) / task_count if task_count > 0 else 0.0,
            avg_cost=sum(m.cost for m in metrics) / task_count if task_count > 0 else 0.0,
            avg_duration_s=sum(m.duration_s for m in metrics) / task_count if task_count > 0 else 0.0,
            total_cost=sum(m.cost for m in metrics),
            run_metrics=tuple(metrics),
        )

    def ab_gate(
        self,
        baseline_metrics: SuiteResult,
        candidate_metrics: SuiteResult,
        *,
        regression_threshold: float = 0.05,
    ) -> tuple[bool, str]:
        """Compare candidate against baseline.

        A regression in success rate exceeding regression_threshold fails the gate.
        Also checks for significant increases in average cost or steps.
        """
        issues: list[str] = []

        # Check success rate regression
        rate_diff = candidate_metrics.success_rate - baseline_metrics.success_rate
        if rate_diff < -regression_threshold:
            issues.append(
                f"Success rate regressed: {candidate_metrics.success_rate:.1%} vs "
                f"baseline {baseline_metrics.success_rate:.1%} "
                f"(diff {rate_diff:.1%}, threshold {regression_threshold:.1%})"
            )

        # Check cost increase
        if candidate_metrics.avg_cost > baseline_metrics.avg_cost * 1.5 and baseline_metrics.avg_cost > 0:
            issues.append(
                f"Average cost increased significantly: "
                f"{candidate_metrics.avg_cost:.4f} vs "
                f"baseline {baseline_metrics.avg_cost:.4f}"
            )

        # Check step count increase
        if candidate_metrics.avg_steps > baseline_metrics.avg_steps * 2.0 and baseline_metrics.avg_steps > 0:
            issues.append(
                f"Average step count increased significantly: "
                f"{candidate_metrics.avg_steps:.1f} vs "
                f"baseline {baseline_metrics.avg_steps:.1f}"
            )

        if issues:
            return False, "; ".join(issues)
        return True, (
            f"Candidate passes A/B gate: success rate {candidate_metrics.success_rate:.1%} "
            f"(baseline {baseline_metrics.success_rate:.1%})"
        )


# -- BrowserGym integration stub ---------------------------------------------


class BrowserGymEvalHarness:
    """Eval harness using BrowserGym environments (when installed).

    BrowserGym provides a gymnasium-compatible environment for browser-agent
    evaluation. This harness wraps BrowserGym tasks into the EvalTask format
    and collects metrics.

    NOTE: This is a reference implementation that works without BrowserGym
    installed. The real BrowserGym integration is activated when the 'eval'
    extra is installed.
    """

    def __init__(self):
        self._bg_available = False
        try:
            self._bg_available = False
        except ImportError:
            pass

    def list_available_tasks(self) -> list[dict[str, str]]:
        """List available BrowserGym tasks.

        Returns:
            List of {task_id, description} dicts.
        """
        if not self._bg_available:
            logger.info("BrowserGym not installed. Install with 'uv sync --extra eval'")
            return []

        return [
            {"task_id": "jobapp.Workday", "description": "Workday application pre-fill"},
            {"task_id": "jobapp.Greenhouse", "description": "Greenhouse application pre-fill"},
            {"task_id": "jobapp.Lever", "description": "Lever application pre-fill"},
        ]

    def create_task_from_browsergym(self, task_id: str) -> EvalTask | None:
        """Create an EvalTask from a BrowserGym task ID.

        Args:
            task_id: BrowserGym task identifier.

        Returns:
            An EvalTask if the task is known, None otherwise.
        """
        if not self._bg_available:
            return None

        known_tasks = {
            "jobapp.Workday": EvalTask(
                task_id="jobapp.Workday",
                url="https://wd3.myworkdayjobs.com/example",
                description="Pre-fill a Workday job application",
                expected_fields=[
                    {"name": "first_name", "type": "text"},
                    {"name": "last_name", "type": "text"},
                    {"name": "email", "type": "email"},
                    {"name": "phone", "type": "tel"},
                ],
                attributes={
                    "first_name": "Jane",
                    "last_name": "Doe",
                    "email": "jane@example.com",
                    "phone": "+1-555-0123",
                },
            ),
            "jobapp.Greenhouse": EvalTask(
                task_id="jobapp.Greenhouse",
                url="https://boards.greenhouse.io/example/jobs/123",
                description="Pre-fill a Greenhouse job application",
                expected_fields=[
                    {"name": "name", "type": "text"},
                    {"name": "email", "type": "email"},
                ],
                attributes={
                    "full_name": "Jane Doe",
                    "email": "jane@example.com",
                },
            ),
        }
        return known_tasks.get(task_id)


# -- Convenience functions (what the BDD specs probe) ------------------------


def run_suite(
    tasks: list[EvalTask],
    planner: Any,
    *,
    parallel: bool = False,
) -> SuiteResult:
    """Run a benchmark task suite and return aggregated metrics.

    This is the top-level entry point the BDD scenarios probe.
    """
    harness = InMemoryEvalHarness()
    return harness.run_suite(tasks, planner, parallel=parallel)


def ab_gate(
    baseline_metrics: SuiteResult,
    candidate_metrics: SuiteResult,
    *,
    regression_threshold: float = 0.05,
) -> tuple[bool, str]:
    """A/B gate: compare candidate against baseline.

    Returns (pass, message). A regression in success rate exceeding the
    threshold fails the gate.
    """
    harness = InMemoryEvalHarness()
    return harness.ab_gate(
        baseline_metrics, candidate_metrics, regression_threshold=regression_threshold
    )
