"""DurableOrchestration port (FR-DUR-1/2/3/4).

DBOS Transact is the chosen backbone: each application is a durable workflow,
each small idempotent step is checkpointed (mid-step resumption), queues enforce
concurrency/rate limits, and send/recv implement approval gates. The DEFAULT
adapter is a DB/file-backed checkpoint shim (no running Postgres required) so the
suite is green; the DBOS-backed adapter is used in real deployments.

A workflow registered here MUST resume from its last completed step after a crash
(FR-DUR-1). Steps must be idempotent.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class WorkflowHandle(Protocol):
    """Handle to a (possibly resumed) durable workflow execution."""

    @property
    def workflow_id(self) -> str: ...

    def result(self) -> Any:
        """Block for and return the workflow result (after any resumptions)."""
        ...


@runtime_checkable
class DurableOrchestrationPort(Protocol):
    """Outbound port for durable, resumable execution."""

    def register_workflow(self, name: str, fn: Callable[..., Any]) -> None:
        """Register a workflow function under ``name``."""
        ...

    def start_workflow(self, name: str, workflow_id: str, *args: Any, **kwargs: Any) -> WorkflowHandle:
        """Start (or resume, if ``workflow_id`` exists) a durable workflow (FR-DUR-1)."""
        ...

    def run_step(self, workflow_id: str, step_name: str, fn: Callable[[], Any]) -> Any:
        """Run an idempotent step once, checkpointing its result.

        On a re-execution after a crash, a previously completed step returns its
        checkpointed result WITHOUT re-running ``fn`` (true mid-step resumption).
        """
        ...

    def send(self, workflow_id: str, topic: str, payload: Any) -> None:
        """Deliver a message to a waiting workflow (approval gate, FR-DUR-3)."""
        ...

    def recv(self, workflow_id: str, topic: str, timeout: float | None = None) -> Any:
        """Wait for a message on ``topic`` (durable wait survives a crash)."""
        ...

    def recover_pending(self) -> list[str]:
        """On startup, resume all interrupted workflows; return their ids (FR-DUR-1)."""
        ...

    def create_queue(
        self,
        name: str,
        *,
        concurrency: int | None = None,
        limiter_limit: int | None = None,
        limiter_period: float | None = None,
    ) -> Any:
        """Create a durable queue with an optional concurrency cap + rate limiter.

        Backs sandbox-concurrency caps and per-provider LLM rate limits (FR-DUR-2).
        Returns a handle whose semantics the adapter defines (DBOS ``Queue`` when
        configured; an in-process semaphore/limiter on the shim).
        """
        ...

    def acquire(self, queue_name: str, work_id: str) -> bool:
        """Try to admit ``work_id`` onto ``queue_name`` (concurrency/rate gate).

        Returns True if admitted (capacity available + within rate limit), False if
        the work must wait. Idempotent per ``work_id`` (re-acquiring an already-held
        slot returns True without consuming a second slot).
        """
        ...

    def release(self, queue_name: str, work_id: str) -> str | None:
        """Release ``work_id``'s slot; admit the next waiter if any (FR-DUR-4).

        Returns the ``work_id`` promoted off the wait-queue (the pivot), or ``None``.
        """
        ...
