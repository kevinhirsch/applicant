"""Durable-workflow integration: the application pipeline resumes from last checkpoint.

Simulates a worker kill mid-workflow by raising inside a step on the first run,
then re-running with a BRAND-NEW orchestrator instance pointed at the SAME
checkpoint directory (modelling a process restart). Already-completed steps must
NOT re-execute (they were checkpointed), proving true mid-step resumption
(FR-DUR-1/3). The real per-application pipeline (open sandbox -> pre-fill ->
material -> final approval via recv -> submit -> teardown) is exercised on the shim.
"""

from __future__ import annotations

import pytest

from applicant.adapters.orchestration.checkpoint_shim import CheckpointShimOrchestrator
from applicant.application.workflows.application_pipeline import (
    FINAL_APPROVAL_TOPIC,
    WORKFLOW_NAME,
    PipelineContext,
    register,
    run_pipeline,
)


class _Kill(Exception):
    pass


def _ctx(executed: list[str], *, kill_on: str | None = None) -> PipelineContext:
    """A pipeline context whose steps record execution (and optionally crash)."""

    def step(name: str, value: dict):
        def _fn():
            executed.append(name)
            if kill_on == name:
                raise _Kill()
            return value

        return _fn

    return PipelineContext(
        application_id="app-42",
        prefill=step("prefill", {"state": "AWAITING_FINAL_APPROVAL"}),
        material_warranted=lambda: False,
        request_final_approval=step("request_approval", None),
        submit=lambda decision: (executed.append("submit") or {"recorded": True}),
        teardown=lambda: executed.append("teardown"),
    )


@pytest.mark.integration
def test_workflow_resumes_from_last_checkpoint(tmp_path):
    ckpt = str(tmp_path / "ckpt")
    wf_id = "app-42"

    # --- run 1: complete pre-fill, then "die" inside submit -------------------
    orch1 = CheckpointShimOrchestrator(ckpt)
    executed_run1: list[str] = []

    def run_until_kill(orch, workflow_id):
        # Pre-fill + final-approval request checkpoint; deliver the decision; then
        # crash inside submit BEFORE it checkpoints.
        orch.run_step(workflow_id, "prefill", lambda: executed_run1.append("prefill") or {"state": "AWAITING_FINAL_APPROVAL"})
        orch.run_step(workflow_id, "material", lambda: executed_run1.append("material") or {"warranted": False})
        orch.run_step(workflow_id, "request_approval", lambda: executed_run1.append("request_approval") or {"notify_handle": None})

        def boom():
            executed_run1.append("submit")
            raise _Kill()

        orch.run_step(workflow_id, "submit", boom)

    orch1.register_workflow(WORKFLOW_NAME, run_until_kill)
    with pytest.raises(_Kill):
        orch1.start_workflow(WORKFLOW_NAME, wf_id)

    # Pre-fill / material / request_approval are checkpointed; submit is not.
    assert orch1.completed_steps(wf_id) == ["prefill", "material", "request_approval"]
    assert executed_run1 == ["prefill", "material", "request_approval", "submit"]

    # --- run 2: NEW orchestrator (process restart) resumes from disk ----------
    orch2 = CheckpointShimOrchestrator(ckpt)
    register(orch2)
    # Deliver the final-approval decision so the recv gate unblocks on resume.
    orch2.send(wf_id, FINAL_APPROVAL_TOPIC, {"decision": "finished_by_engine"})
    executed_run2: list[str] = []
    handle = orch2.start_workflow(WORKFLOW_NAME, wf_id, ctx=_ctx(executed_run2))

    result = handle.result()
    assert result["status"] == "done"
    # Pre-fill / material / request_approval did NOT re-run; only submit + teardown did.
    assert executed_run2 == ["submit", "teardown"]
    assert set(orch2.completed_steps(wf_id)) == {
        "prefill",
        "material",
        "request_approval",
        "submit",
        "teardown",
    }


@pytest.mark.integration
def test_recover_pending_finds_interrupted_workflow(tmp_path):
    ckpt = str(tmp_path / "ckpt2")
    orch = CheckpointShimOrchestrator(ckpt)
    register(orch)
    orch.send("app-99", FINAL_APPROVAL_TOPIC, {"decision": "finished_by_engine"})
    orch.start_workflow(WORKFLOW_NAME, "app-99", ctx=_ctx([]))
    # A fresh orchestrator (restart) can find the workflow's checkpoint.
    assert "app-99" in CheckpointShimOrchestrator(ckpt).recover_pending()


@pytest.mark.integration
def test_pipeline_handoff_yields_on_blocked(tmp_path):
    """A BLOCKED_* pre-fill state stops the pass so the loop can pivot (FR-DUR-4)."""
    orch = CheckpointShimOrchestrator(str(tmp_path / "ckpt3"))
    executed: list[str] = []
    ctx = PipelineContext(
        application_id="app-1",
        prefill=lambda: (executed.append("prefill") or {"state": "BLOCKED_QUESTION"}),
        submit=lambda d: {"recorded": True},
    )
    result = run_pipeline(orch, "wf", ctx=ctx)
    assert result["status"] == "handoff"
    assert result["handoff_state"] == "BLOCKED_QUESTION"
    # Pre-fill ran; submit/teardown did not (yielded for the human-in-the-loop point).
    assert executed == ["prefill"]
