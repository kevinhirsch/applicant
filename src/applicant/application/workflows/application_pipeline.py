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
from applicant.core.state_machine import TERMINAL_STATES
from applicant.observability.logging import get_logger

log = get_logger(__name__)

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

#: Public alias (P2-12 durability drill finding): the caller (``AgentLoop.
#: _apply_outcome``) needs this SAME set to decide whether a hand-off must clear the
#: workflow's durable checkpoint before the next re-drive — see the long comment on
#: that branch for why. Reuses this module's existing set rather than a second
#: hard-coded copy of the same five state names.
PREFILL_HANDOFF_STATES = _HANDOFF_STATES

#: P2-12 durability drill finding: a pre-fill that already landed in a §7 TERMINAL
#: state (``FAILED`` — "any unrecoverable error", e.g. a crashed browser tab/context
#: mid-walk, see #207/#336) must stop the pipeline HERE, exactly like a hand-off.
#: Before this check existed, a terminally-FAILED pre-fill fell through to material
#: generation + a final-approval request for an application that had already died —
#: and if a human then approved it, ``submit`` raised ``IllegalStateTransition``
#: (FAILED is not a legal ``AWAITING_FINAL_APPROVAL`` pre-state) every single retry,
#: forever, with the sandbox slot never released (DUR-2 leak). Reuses the SAME
#: ``TERMINAL_STATES`` the rest of the state machine already treats as terminal
#: (``core/state_machine.py``) rather than inventing a parallel notion of "done".
_TERMINAL_STATE_VALUES = frozenset(s.value for s in TERMINAL_STATES)


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
    #: -> bool: whether ALL generated material for the app is now approved. Re-evaluated
    #: OUTSIDE the checkpointed ``material`` step on every re-drive (#1) so a stale
    #: cached "not approved" can never park the pipeline before the recv gate forever.
    material_approved: Callable[[], bool] | None = None
    #: -> str|None: the application's CURRENT persisted §7 state (read live from
    #: storage — the durable source of truth). Mirrors ``material_approved`` (#1):
    #: consulted OUTSIDE the checkpointed ``prefill`` step whenever that step served
    #: a CACHED hand-off, so a stale checkpoint can never lock the pipeline at the
    #: wall on an orchestrator that cannot clear a completed step (Greptile P1 on
    #: PR #767: the DBOS adapter exposes no ``clear``, so the run loop's
    #: checkpoint-clear-on-handoff silently no-ops there). ``None`` (default)
    #: preserves the exact prior behavior (side_effects-only resumption tests).
    persisted_state: Callable[[], str | None] | None = None
    #: -> str|None: notify the user the app awaits final approval (returns notify handle).
    request_final_approval: Callable[[], Any] | None = None
    #: -> dict: record the submission/outcome once approval is delivered.
    submit: Callable[[dict], dict] | None = None
    #: -> None: tear down the sandbox / clean up. Wrapped to be idempotent (see below).
    teardown: Callable[[], None] | None = None
    #: timeout (seconds) for the durable final-approval ``recv`` wait.
    approval_timeout: float | None = None

    #: #221 — teardown is idempotent BY CONTRACT. The terminal teardown step can be
    #: re-driven after a crash in the window AFTER the sandbox was released but BEFORE its
    #: checkpoint was written; a non-idempotent callback would then raise on (or worse,
    #: double-release) an already-destroyed sandbox. ``__post_init__`` wraps the supplied
    #: callback so the FIRST call runs it (swallowing an "already released" error as a
    #: success, since the desired end-state — sandbox gone — already holds) and every
    #: later call is a guaranteed no-op. Callers/tests may rely on this flag.
    teardown_idempotent: bool = True

    def __post_init__(self) -> None:
        # Make teardown at-least-once safe: re-driving the terminal step must never
        # double-release or raise on an already-torn-down sandbox (#221).
        raw = self.teardown
        if raw is None:
            return
        done = {"flag": False}

        def _idempotent_teardown() -> None:
            if done["flag"]:
                return  # already torn down this process — contract-guaranteed no-op.
            try:
                raw()
            except Exception as exc:  # noqa: BLE001 - any "already released" signal
                # The end-state we want (sandbox gone) already holds; a re-drive after a
                # crash-before-checkpoint must not surface as a failure. Record + swallow.
                log.warning(
                    "teardown_idempotent_swallowed",
                    application_id=self.application_id,
                    error=str(exc),
                )
            finally:
                done["flag"] = True

        # ``object.__setattr__`` keeps this robust even if the dataclass is frozen later.
        object.__setattr__(self, "teardown", _idempotent_teardown)


def _is_handoff(state: str | None) -> bool:
    return state in _HANDOFF_STATES


def _is_terminal(state: str | None) -> bool:
    return state in _TERMINAL_STATE_VALUES


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
    workflow resumes from its last checkpoint once the user resolves the gate. When
    pre-fill instead lands a §7 TERMINAL state (``FAILED`` — an unrecoverable error,
    e.g. a crashed browser mid-walk), the pipeline tears down and returns early
    (``status="failed"``) rather than generating material / requesting approval for
    an application that already died (P2-12 durability drill finding).

    ``side_effects`` (optional) records which step bodies actually executed this run
    so a resumption test can prove already-checkpointed steps were skipped.
    """
    sink = side_effects if side_effects is not None else []
    out: dict[str, Any] = {"workflow_id": workflow_id}

    # 1. Open sandbox + maximal pre-fill (one checkpointed step). ------------
    executed_this_pass = {"prefill": False}

    def _prefill() -> dict:
        executed_this_pass["prefill"] = True
        sink.append("prefill")
        if ctx is not None and ctx.prefill is not None:
            return ctx.prefill()
        return {"state": "AWAITING_FINAL_APPROVAL"}

    prefill_result = orchestrator.run_step(workflow_id, "prefill", _prefill)

    # Greptile P1 (PR #767): a CACHED hand-off must not be trusted blindly. The run
    # loop clears the checkpoint after a pre-fill hand-off so the next drive re-runs
    # the step — but only on orchestrators that expose ``clear`` (the shim). On a
    # backend without it (the DBOS adapter has no ``clear``, and DBOS's exactly-once
    # step recording cannot be reset through its public API), the stale checkpointed
    # hand-off would replay on every re-drive FOREVER, so an application could never
    # leave the wall even after the human resolved it — the exact lockout the P2-12
    # CAPTCHA drill first found on the shim. Mirror the ``material_approved`` (#1)
    # pattern: when the step was served from cache AND it claims a hand-off, re-read
    # the PERSISTED §7 state (the durable source of truth) live:
    #   * still parked at a hand-off  -> re-drive pre-fill LIVE (``ctx.prefill`` —
    #     the run loop's closure picks the targeted ``resume_after_*`` entry, #4);
    #   * already past the wall       -> trust the persisted state and continue
    #     (the checkpoint is only a cache of it).
    # No live source wired (``persisted_state=None`` — the side_effects-only
    # resumption tests) keeps the exact prior cached behavior.
    if (
        _is_handoff(prefill_result.get("state"))
        and not executed_this_pass["prefill"]
        and ctx is not None
        and ctx.persisted_state is not None
    ):
        live_state = ctx.persisted_state()
        if _is_handoff(live_state) and ctx.prefill is not None:
            log.info(
                "prefill_handoff_checkpoint_stale_redriving_live",
                workflow_id=workflow_id,
                cached_state=prefill_result.get("state"),
                live_state=live_state,
            )
            prefill_result = _prefill()
        elif live_state is not None and not _is_handoff(live_state):
            prefill_result = {"state": live_state}

    out["prefill"] = prefill_result

    # Human-in-the-loop hand-off: yield + stop this pass (FR-AGENT-4/6, FR-DUR-4).
    if _is_handoff(prefill_result.get("state")):
        out["status"] = "handoff"
        out["handoff_state"] = prefill_result.get("state")
        return out

    # P2-12 durability drill finding: a TERMINAL pre-fill outcome (FAILED) stops the
    # pipeline here too — material/approval/submit are meaningless (and unsafe: a
    # later approve would raise IllegalStateTransition forever, see the module-level
    # comment on ``_TERMINAL_STATE_VALUES``). Still tear down (as its own checkpointed,
    # idempotent step) so the sandbox slot is released exactly like the ``done`` path.
    if _is_terminal(prefill_result.get("state")):
        out["status"] = "failed"
        out["failure_state"] = prefill_result.get("state")

        def _terminal_teardown() -> dict:
            sink.append("teardown")
            if ctx is not None and ctx.teardown is not None:
                ctx.teardown()
            return {"torn_down": True}

        out["teardown"] = orchestrator.run_step(workflow_id, "teardown", _terminal_teardown)
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
    #
    # #1: re-evaluate approval OUTSIDE the checkpointed ``material`` step. The step's
    # result is cached on first run with ``review_approved=False`` (nothing approved
    # yet); serving that cache forever would park the pipeline before the recv gate
    # permanently. On every re-drive, ``ctx.material_approved`` re-reads approval from
    # storage so an actual approval advances the workflow. Falls back to the
    # checkpointed flag only when no live re-check callable is wired (the resumption
    # test's side_effects-only mode).
    if material_result.get("warranted"):
        approved = material_result.get("review_approved")
        if ctx is not None and ctx.material_approved is not None:
            approved = ctx.material_approved()
        if not approved:
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
