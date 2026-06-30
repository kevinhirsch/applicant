"""Browser-agent eval harness for the pre-fill planner (Issue #309).

An A/B regression gate for the plan-as-data planner. ``run_suite`` runs the
planner over a benchmark task suite and reports the metrics that matter for a
browser agent — **success rate, step count, and cost** — per run. ``ab_gate``
compares a candidate run against a baseline and fails the gate on a success-rate
regression, so a planner change that makes the agent worse cannot land.

This is the harness skeleton (AgentLab / BrowserGym style): a task is a callable
that, given the planner, returns whether the plan succeeded plus the steps and
cost it took. The harness is pure orchestration + metric aggregation — no browser
or network — so it runs in the hermetic lane and in CI as a gate.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field


@dataclass(frozen=True)
class TaskResult:
    """The outcome of running one benchmark task through a planner."""

    task_id: str
    success: bool
    steps: int = 0
    cost: float = 0.0


@dataclass(frozen=True)
class SuiteReport:
    """Aggregate metrics for one planner run over the benchmark suite (#309)."""

    success_rate: float
    avg_steps: float
    total_cost: float
    n_tasks: int
    results: tuple[TaskResult, ...] = field(default_factory=tuple)


#: A benchmark task: given a planner, run it and report (success, steps, cost).
BenchmarkTask = Callable[[object], TaskResult]


def run_suite(planner: object, tasks: Sequence[BenchmarkTask]) -> SuiteReport:
    """Run ``planner`` over ``tasks`` and report success-rate / steps / cost (#309).

    Each task is invoked with the planner and returns a :class:`TaskResult`.
    The report aggregates the success rate, average step count, and total cost
    across the suite — the per-run metrics a planner change is judged on.
    """
    results: list[TaskResult] = []
    for task in tasks:
        try:
            result = task(planner)
        except Exception as exc:  # a crashing task is a failed task, not a crash
            results.append(TaskResult(task_id=getattr(task, "__name__", "task"), success=False))
            _ = exc
            continue
        results.append(result)

    n = len(results)
    if n == 0:
        return SuiteReport(success_rate=0.0, avg_steps=0.0, total_cost=0.0, n_tasks=0)

    successes = sum(1 for r in results if r.success)
    return SuiteReport(
        success_rate=successes / n,
        avg_steps=sum(r.steps for r in results) / n,
        total_cost=sum(r.cost for r in results),
        n_tasks=n,
        results=tuple(results),
    )


@dataclass(frozen=True)
class GateResult:
    """The A/B gate decision for a candidate planner change (#309)."""

    passed: bool
    baseline_success_rate: float
    candidate_success_rate: float
    reason: str = ""


def ab_gate(
    baseline: SuiteReport,
    candidate: SuiteReport,
    *,
    tolerance: float = 0.0,
) -> GateResult:
    """A/B-gate a candidate planner run against the baseline (#309).

    The gate **fails** when the candidate's success rate drops below the
    baseline's (beyond ``tolerance``) — a success-rate regression must not land.
    A candidate that matches or improves the baseline passes.
    """
    delta = candidate.success_rate - baseline.success_rate
    if delta < -tolerance:
        return GateResult(
            passed=False,
            baseline_success_rate=baseline.success_rate,
            candidate_success_rate=candidate.success_rate,
            reason=(
                f"success rate regressed {baseline.success_rate:.2%} -> "
                f"{candidate.success_rate:.2%}"
            ),
        )
    return GateResult(
        passed=True,
        baseline_success_rate=baseline.success_rate,
        candidate_success_rate=candidate.success_rate,
        reason="no success-rate regression",
    )
