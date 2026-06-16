"""Trivial durable application pipeline demonstrating mid-step resumption (FR-DUR-1/3).

# STAGE B — Phase 0 deepens this into the full §7 pipeline (one DBOS step per
# lifecycle transition). Today it is intentionally trivial: two idempotent steps
# that checkpoint their results so a kill/restart resumes from the last completed
# step rather than re-running prior work.

The workflow runs ENTIRELY through the ``DurableOrchestrationPort`` so the same
code works on the file-backed shim (default, no Postgres) and on DBOS later.

``run_pipeline`` is the registered workflow function: the orchestrator passes
itself and the ``workflow_id`` as the first two arguments.
"""

from __future__ import annotations

from typing import Any

WORKFLOW_NAME = "application_pipeline"


def run_pipeline(orchestrator: Any, workflow_id: str, *, side_effects: list[str] | None = None) -> dict:
    """Two-step durable pipeline.

    ``side_effects`` (optional) records which steps *actually executed* their body
    in this run — on a resumption, already-checkpointed steps must NOT append to
    it (proving they were skipped). Returns the accumulated step results.
    """
    sink = side_effects if side_effects is not None else []

    def step_one() -> dict:
        sink.append("step_one")
        return {"step": "one", "value": 1}

    def step_two() -> dict:
        sink.append("step_two")
        return {"step": "two", "value": 2}

    r1 = orchestrator.run_step(workflow_id, "step_one", step_one)
    r2 = orchestrator.run_step(workflow_id, "step_two", step_two)
    return {"step_one": r1, "step_two": r2}


def register(orchestrator: Any) -> None:
    """Register the pipeline workflow with an orchestrator."""
    orchestrator.register_workflow(WORKFLOW_NAME, run_pipeline)
