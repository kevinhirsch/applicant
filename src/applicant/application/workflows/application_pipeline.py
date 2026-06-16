"""Real per-application durable workflow (FR-DUR-1/3, §7 lifecycle).

This is the per-application pipeline that the agent run loop enqueues for every
APPROVED digest item. It runs ENTIRELY through the ``DurableOrchestrationPort`` so
the same code executes on the file-backed shim (default, no Postgres) and on DBOS.

Each lifecycle move is its own **idempotent, individually-checkpointed step**
(``orchestrator.run_step``): on a kill/restart, completed steps return their
checkpointed result WITHOUT re-running their body (mid-step resumption, FR-DUR-1).
The shape of the pipeline mirrors docs/state-machine.md §7:

    open sandbox -> maximal pre-fill -> [generate + review material if warranted]
    -> await final approval via ``recv`` -> submit / record outcome -> teardown

The orchestrator passes ``(orchestrator, workflow_id, **kwargs)`` to the registered
workflow. The work is supplied via a ``ctx`` (a :class:`PipelineContext`) so the
pure orchestration logic is decoupled from the concrete services; the run loop
builds a context bound to the live services. Callers that only need the
resumption contract (the durable-workflow test) may pass ``side_effects`` and no
``ctx`` — the steps then degrade to recording which step bodies executed, which is
exactly what proves mid-step resumption.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from applicant.application.services.prefill_service import FINAL_APPROVAL_TOPIC

WORKFLOW_NAME = "application_pipeline"

#: §7 hand-off states where the application yields capacity and the pipeline
#: stops this pass (a human-in-the-loop point). The run loop pivots to other work
#: and the workflow resumes when the user resolves the gate. ``AWAITING_FINAL_APPROVAL``
#: is NOT a hand-off here — it is the normal end of pre-fill and flows into the
#: pipeline's own final-approval gate.
_HANDOFF_STATES = frozenset(
    {
        "BLOCKED_DETECTION",
        "BLOCKED_MISSING_ATTR",
        "BLOCKED_QUESTION",
        "AWAITING_ACCOUNT_HUMAN_STEP",
        "EMERGENCY_DATA_HANDOFF",
    }
)


@dataclass
class PipelineContext:
    """Live work bound to one application's durable pipeline.

    Every field is a small callable so the workflow body stays orchestration-only
    and each maps to exactly one idempotent step. All are optional so the trivial
    resumption test can drive the workflow with ``side_effects`` alone.
    """

    application_id: str = ""
    #: -> dict with at least {"state": <ApplicationState value>}; opens sandbox + pre-fills.
    prefill: Callable[[], dict] | None = None
    #: -> bool: whether this role warrants generated material (resume / cover letter).
    material_warranted: Callable[[], bool] | None = None
    #: -> dict: generate material + route to MATERIAL_REVIEW (returns a small summary).
    prepare_material: Callable[[], dict] | None = None
    #: -> str|None: notify the user the app awaits final approval (returns notify handle).
    request_final_approval: Callable[[], Any] | None = None
    #: -> dict: record the submission/outcome once approval is delivered.
    submit: Callable[[dict], dict] | None = None
    #: -> None: tear down the sandbox / clean up.
    teardown: Callable[[], None] | None = None
    #: timeout (seconds) for the durable final-approval ``recv`` wait.
    approval_timeout: float | None = None


def _is_handoff(state: str | None) -> bool:
    return state in _HANDOFF_STATES


def run_pipeline(
    orchestrator: Any,
    workflow_id: str,
    *,
    ctx: PipelineContext | None = None,
    side_effects: list[str] | None = None,
) -> dict:
    """The real per-application durable pipeline (FR-DUR-1/3).

    Returns a dict summarizing each completed step. When the pre-fill step lands a
    ``BLOCKED_*`` / ``AWAITING_*`` / ``EMERGENCY_*`` hand-off state, the pipeline
    returns early (``status="handoff"``) so the run loop pivots to other work; the
    workflow resumes from its last checkpoint once the user resolves the gate.

    ``side_effects`` (optional) records which step bodies actually executed this run
    so a resumption test can prove already-checkpointed steps were skipped.
    """
    sink = side_effects if side_effects is not None else []
    out: dict[str, Any] = {"workflow_id": workflow_id}

    # 1. Open sandbox + maximal pre-fill (one checkpointed step). ------------
    def _prefill() -> dict:
        sink.append("prefill")
        if ctx is not None and ctx.prefill is not None:
            return ctx.prefill()
        return {"state": "AWAITING_FINAL_APPROVAL"}

    prefill_result = orchestrator.run_step(workflow_id, "prefill", _prefill)
    out["prefill"] = prefill_result

    # Human-in-the-loop hand-off: yield + stop this pass (FR-AGENT-4/6, FR-DUR-4).
    if _is_handoff(prefill_result.get("state")):
        out["status"] = "handoff"
        out["handoff_state"] = prefill_result.get("state")
        return out

    # 2. Generate + review material when the role warrants it (FR-RESUME-1/8). -
    def _material() -> dict:
        sink.append("material")
        if ctx is None:
            return {"warranted": False}
        warranted = ctx.material_warranted() if ctx.material_warranted else False
        if not warranted:
            return {"warranted": False}
        summary = ctx.prepare_material() if ctx.prepare_material else {}
        return {"warranted": True, **(summary or {})}

    material_result = orchestrator.run_step(workflow_id, "material", _material)
    out["material"] = material_result
    # Material routed to review is itself a human-in-the-loop gate (MATERIAL_REVIEW):
    # yield and resume after the user approves the redline.
    if material_result.get("warranted") and not material_result.get("review_approved"):
        out["status"] = "handoff"
        out["handoff_state"] = "MATERIAL_REVIEW"
        return out

    # 3. Request final approval (escalation ladder) + durably wait (FR-NOTIF-2). -
    def _request_approval() -> dict:
        sink.append("request_approval")
        handle = None
        if ctx is not None and ctx.request_final_approval is not None:
            handle = ctx.request_final_approval()
        return {"notify_handle": handle}

    out["request_approval"] = orchestrator.run_step(
        workflow_id, "request_approval", _request_approval
    )

    # The durable gate itself is NOT a checkpointed step (it is a recv); a crash
    # while waiting resumes the recv on restart (FR-DUR-1/3).
    timeout = ctx.approval_timeout if ctx is not None else None
    decision = orchestrator.recv(workflow_id, FINAL_APPROVAL_TOPIC, timeout=timeout)
    if decision is None:
        # No decision yet — yield; the scheduler re-notifies via the ladder and the
        # workflow resumes the wait on the next pass (FR-AGENT-4, FR-NOTIF-2).
        out["status"] = "awaiting_final_approval"
        return out
    out["decision"] = decision

    # 4. Submit / record the outcome (terminal, FR-LOG-1/4). ------------------
    def _submit() -> dict:
        sink.append("submit")
        if ctx is not None and ctx.submit is not None:
            return ctx.submit(decision)
        return {"recorded": True}

    out["submit"] = orchestrator.run_step(workflow_id, "submit", _submit)

    # 5. Teardown (idempotent). ----------------------------------------------
    def _teardown() -> dict:
        sink.append("teardown")
        if ctx is not None and ctx.teardown is not None:
            ctx.teardown()
        return {"torn_down": True}

    out["teardown"] = orchestrator.run_step(workflow_id, "teardown", _teardown)
    out["status"] = "done"
    return out


def register(orchestrator: Any) -> None:
    """Register the pipeline workflow with an orchestrator."""
    orchestrator.register_workflow(WORKFLOW_NAME, run_pipeline)
