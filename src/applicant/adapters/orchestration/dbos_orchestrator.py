"""DBOS Transact durable-orchestration adapter (FR-DUR-1/2/3).

DBOS co-resides workflow/step state in the same Postgres (FR-DUR-3), giving true
mid-step resumption, durable queues (concurrency / rate-limit), send/recv approval
gates, and scheduling for cron-like work. DBOS requires a live Postgres at launch,
so the DEFAULT adapter is the file-backed ``CheckpointShimOrchestrator`` (keeps the
test suite green); this adapter is selected when ``ORCHESTRATOR_BACKEND=dbos``.

The ``dbos`` package import is deferred to ``_ensure_launched`` so importing this
module never touches Postgres — the app boots on the shim regardless.

Bridging the dynamic port to DBOS decorators
--------------------------------------------
The port is dynamic (``register_workflow(name, fn)`` / ``run_step(wf, step, fn)``)
whereas DBOS is decorator-based. We bridge by:

* wrapping each registered workflow body in a single ``@DBOS.workflow`` shim that
  receives ``(self, workflow_id, *args, **kwargs)`` and calls the user fn;
* running each idempotent step inside ``DBOS.run_step`` (deterministic by
  ``step_name``) so completed steps return their checkpointed result on resume;
* delegating ``send``/``recv`` and ``recover_pending`` straight to DBOS.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class _DbosHandle:
    def __init__(self, workflow_id: str, handle: Any) -> None:
        self._workflow_id = workflow_id
        self._handle = handle

    @property
    def workflow_id(self) -> str:
        return self._workflow_id

    def result(self) -> Any:
        return self._handle.get_result() if self._handle is not None else None


class DbosOrchestrator:
    """DurableOrchestrationPort backed by DBOS Transact."""

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url
        self._launched = False
        self._dbos: Any = None
        self._workflows: dict[str, Callable[..., Any]] = {}
        self._wf_shims: dict[str, Callable[..., Any]] = {}

    def _ensure_launched(self) -> None:
        if self._launched:
            return
        # Deferred import: only touch DBOS / Postgres when actually used.
        from dbos import DBOS, DBOSConfig

        config: DBOSConfig = {
            "name": "applicant",
            "database_url": self._database_url,
        }
        DBOS(config=config)
        DBOS.launch()
        self._dbos = DBOS
        self._launched = True

    def register_workflow(self, name: str, fn: Callable[..., Any]) -> None:
        """Register ``fn`` as a DBOS durable workflow under ``name`` (FR-DUR-1)."""
        self._ensure_launched()
        from dbos import DBOS

        self._workflows[name] = fn

        # The shim is the DBOS workflow; it forwards to the registered fn with this
        # orchestrator as the runner (so fn calls back into run_step/send/recv).
        @DBOS.workflow(name=f"applicant.{name}")
        def _shim(workflow_id: str, *args: Any, **kwargs: Any) -> Any:
            return self._workflows[name](self, workflow_id, *args, **kwargs)

        self._wf_shims[name] = _shim

    def start_workflow(self, name: str, workflow_id: str, *args: Any, **kwargs: Any) -> _DbosHandle:
        """Start (or resume, by idempotent ``workflow_id``) a durable workflow."""
        self._ensure_launched()
        from dbos import DBOS, SetWorkflowID

        shim = self._wf_shims.get(name)
        if shim is None:
            raise KeyError(f"workflow not registered: {name}")
        with SetWorkflowID(workflow_id):
            handle = DBOS.start_workflow(shim, workflow_id, *args, **kwargs)
        return _DbosHandle(workflow_id, handle)

    def run_step(self, workflow_id: str, step_name: str, fn: Callable[[], Any]) -> Any:
        """Run an idempotent, checkpointed DBOS step (mid-step resumption)."""
        self._ensure_launched()
        from dbos import DBOS

        return DBOS.run_step(fn, name=step_name)

    def send(self, workflow_id: str, topic: str, payload: Any) -> None:
        """Deliver an approval-gate message to a waiting workflow (FR-DUR-3)."""
        self._ensure_launched()
        from dbos import DBOS

        DBOS.send(workflow_id, payload, topic=topic)

    def recv(self, workflow_id: str, topic: str, timeout: float | None = None) -> Any:
        """Durably wait for a message on ``topic`` (survives a crash)."""
        self._ensure_launched()
        from dbos import DBOS

        return DBOS.recv(topic=topic, timeout_seconds=timeout or 60.0)

    def recover_pending(self) -> list[str]:
        """Resume all interrupted workflows on startup; return their ids (FR-DUR-1)."""
        self._ensure_launched()
        from dbos import DBOS

        handles = DBOS.recover_pending_workflows()
        return [h.workflow_id for h in handles]

    # --- durable queue concept (concurrency caps / rate limits) ----------
    def create_queue(
        self,
        name: str,
        *,
        concurrency: int | None = None,
        limiter_limit: int | None = None,
        limiter_period: float | None = None,
    ) -> Any:
        """Create a durable queue for concurrency caps / LLM rate limits (FR-DUR-2).

        Skeleton: returns a ``dbos.Queue`` configured with an optional global
        concurrency cap and an optional rate limiter (limit per period seconds).
        Phase 2 enqueues sandbox sessions / LLM calls onto these queues.
        """
        self._ensure_launched()
        from dbos import Queue

        limiter = None
        if limiter_limit is not None and limiter_period is not None:
            limiter = {"limit": limiter_limit, "period": limiter_period}
        return Queue(name, concurrency=concurrency, limiter=limiter)

    def schedule(self, name: str, cron: str, fn: Callable[..., Any]) -> Callable[..., Any]:
        """Register a cron-scheduled durable workflow (FR-DUR-3, scheduling).

        Skeleton: wraps ``fn`` with ``@DBOS.scheduled(cron)`` + ``@DBOS.workflow``
        so DBOS fires it on the schedule with crash-safe, exactly-once semantics.
        """
        self._ensure_launched()
        from dbos import DBOS

        @DBOS.scheduled(cron)
        @DBOS.workflow(name=f"applicant.sched.{name}")
        def _scheduled(scheduled_time: Any, actual_time: Any) -> Any:
            return fn(scheduled_time, actual_time)

        return _scheduled
