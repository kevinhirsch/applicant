"""CapacityService — sandbox concurrency cap + LLM rate limit + pivot (FR-DUR-2/4, FR-AGENT-6).

Turns the durable-orchestration queue primitives into the live concurrency policy:

* a **sandbox-concurrency queue** caps how many applications hold a live browser
  sandbox at once (FR-DUR-2);
* a **per-provider LLM queue** enforces a rate limit on LLM calls (FR-DUR-2);
* when an application enters a ``BLOCKED_*`` / ``AWAITING_*`` state it **yields its
  sandbox slot** (``yield_for_block``), which the queue immediately hands to the next
  waiting application — the **pivot-around-blocker** (FR-DUR-4, FR-AGENT-6). One
  blocked/awaiting application therefore never stalls unrelated work.

Works on the file-backed shim by default (no Postgres) and on DBOS when configured —
both implement ``create_queue`` / ``acquire`` / ``release`` behind the port.
"""

from __future__ import annotations

from applicant.core.state_machine import ApplicationState
from applicant.observability.logging import get_logger

log = get_logger(__name__)

SANDBOX_QUEUE = "sandbox_concurrency"
LLM_QUEUE = "llm_rate"

#: §7: every BLOCKED_*/AWAITING_* state yields capacity (pivots).
_YIELDING_STATES = frozenset(
    {
        ApplicationState.AWAITING_ACCOUNT_HUMAN_STEP,
        ApplicationState.BLOCKED_DETECTION,
        ApplicationState.BLOCKED_MISSING_ATTR,
        ApplicationState.BLOCKED_QUESTION,
        ApplicationState.MATERIAL_REVIEW,
        ApplicationState.AWAITING_FINAL_APPROVAL,
        ApplicationState.EMERGENCY_DATA_HANDOFF,
    }
)


class CapacityService:
    def __init__(
        self,
        orchestrator,
        *,
        sandbox_concurrency: int = 3,
        llm_limit: int | None = None,
        llm_period: float | None = None,
    ) -> None:
        self._orch = orchestrator
        # Defense in depth alongside the config ge=1 clamp: never create a 0/negative
        # concurrency queue (it would admit no application and stall all work).
        self._orch.create_queue(SANDBOX_QUEUE, concurrency=max(1, sandbox_concurrency))
        if llm_limit is not None and llm_period is not None:
            self._orch.create_queue(
                LLM_QUEUE, limiter_limit=llm_limit, limiter_period=llm_period
            )

    # --- sandbox concurrency cap (FR-DUR-2) -------------------------------
    def admit_sandbox(self, application_id: str) -> bool:
        """Try to admit an application to a sandbox slot; False -> it must wait."""
        admitted = self._orch.acquire(SANDBOX_QUEUE, str(application_id))
        log.info("sandbox_admission", application_id=str(application_id), admitted=admitted)
        return admitted

    def yield_for_block(self, application_id: str, state: ApplicationState) -> str | None:
        """Yield the sandbox slot when an app blocks/awaits; return the pivoted app.

        This is the live pivot-around-blocker (FR-DUR-4, FR-AGENT-6): a waiting
        application is admitted the moment the blocked one yields its slot.
        """
        if state not in _YIELDING_STATES:
            return None
        promoted = self._orch.release(SANDBOX_QUEUE, str(application_id))
        log.info(
            "sandbox_pivot",
            yielded_by=str(application_id),
            state=state.value,
            promoted=promoted,
        )
        return promoted

    def release_sandbox(self, application_id: str) -> str | None:
        """Release a sandbox slot on terminal completion; promote the next waiter."""
        return self._orch.release(SANDBOX_QUEUE, str(application_id))

    # --- capacity introspection (dark-engine audit #72) --------------------
    def sandbox_queue_state(self) -> dict:
        """Read-only snapshot of who holds a sandbox slot vs. who is waiting.

        Introspects the SAME ``SANDBOX_QUEUE`` primitive ``admit_sandbox`` /
        ``release_sandbox`` drive every tick, via the orchestrator's
        ``queue_state`` (implemented on the default checkpoint-shim backend).
        Defensive: the optional DBOS backend doesn't implement this
        introspection today, so this degrades to an "unsupported" snapshot
        rather than raising — never fabricates counts it cannot read.
        """
        reader = getattr(self._orch, "queue_state", None)
        if reader is None:
            return {"active": [], "waiting": [], "supported": False}
        state = reader(SANDBOX_QUEUE)
        return {
            "active": list(state.get("active", [])),
            "waiting": list(state.get("waiting", [])),
            "supported": True,
        }

    # --- per-provider LLM rate limit (FR-DUR-2) ---------------------------
    def admit_llm(self, call_id: str) -> bool:
        """Try to admit an LLM call within the per-provider rate limit."""
        return self._orch.acquire(LLM_QUEUE, str(call_id))

    def release_llm(self, call_id: str) -> str | None:
        return self._orch.release(LLM_QUEUE, str(call_id))
