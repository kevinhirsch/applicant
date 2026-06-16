"""Durable-workflow integration: the trivial pipeline resumes from last checkpoint.

Simulates a worker kill mid-workflow by raising inside step two on the first run,
then re-running with a BRAND-NEW orchestrator instance pointed at the SAME
checkpoint directory (modelling a process restart). Step one must NOT re-execute
(it was checkpointed), proving true mid-step resumption (FR-DUR-1/3).
"""

from __future__ import annotations

import pytest

from applicant.adapters.orchestration.checkpoint_shim import CheckpointShimOrchestrator
from applicant.application.workflows.application_pipeline import (
    WORKFLOW_NAME,
    register,
    run_pipeline,
)


class _Kill(Exception):
    pass


@pytest.mark.integration
def test_workflow_resumes_from_last_checkpoint(tmp_path):
    ckpt = str(tmp_path / "ckpt")
    wf_id = "app-42"

    # --- run 1: complete step one, then "die" before step two finishes --------
    orch1 = CheckpointShimOrchestrator(ckpt)
    executed_run1: list[str] = []

    def run_until_kill(orch, workflow_id):
        orch.run_step(workflow_id, "step_one", lambda: executed_run1.append("step_one") or {"value": 1})
        # Simulate a crash during step two (before it checkpoints).
        def boom():
            executed_run1.append("step_two")
            raise _Kill()
        orch.run_step(workflow_id, "step_two", boom)

    orch1.register_workflow(WORKFLOW_NAME, run_until_kill)
    with pytest.raises(_Kill):
        orch1.start_workflow(WORKFLOW_NAME, wf_id)

    # Step one is checkpointed; step two is not.
    assert orch1.completed_steps(wf_id) == ["step_one"]
    assert executed_run1 == ["step_one", "step_two"]

    # --- run 2: NEW orchestrator (process restart) resumes from disk ----------
    orch2 = CheckpointShimOrchestrator(ckpt)
    register(orch2)
    side_effects: list[str] = []
    handle = orch2.start_workflow(WORKFLOW_NAME, wf_id, side_effects=side_effects)

    result = handle.result()
    assert result["step_one"] == {"value": 1}  # checkpointed value preserved
    assert result["step_two"] == {"step": "two", "value": 2}

    # Step one did NOT re-run on resume; only step two executed.
    assert side_effects == ["step_two"]
    assert set(orch2.completed_steps(wf_id)) == {"step_one", "step_two"}


@pytest.mark.integration
def test_recover_pending_finds_interrupted_workflow(tmp_path):
    ckpt = str(tmp_path / "ckpt2")
    orch = CheckpointShimOrchestrator(ckpt)
    register(orch)
    orch.start_workflow(WORKFLOW_NAME, "app-99")
    # A fresh orchestrator (restart) can find the workflow's checkpoint.
    assert "app-99" in CheckpointShimOrchestrator(ckpt).recover_pending()


@pytest.mark.integration
def test_pipeline_happy_path(tmp_path):
    orch = CheckpointShimOrchestrator(str(tmp_path / "ckpt3"))
    side: list[str] = []
    result = run_pipeline(orch, "wf", side_effects=side)
    assert result["step_one"]["value"] == 1
    assert side == ["step_one", "step_two"]
