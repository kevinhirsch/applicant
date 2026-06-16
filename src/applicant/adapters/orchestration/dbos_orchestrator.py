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

import time
from collections import deque
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
        # Admission bookkeeping mirrors the DBOS queue concurrency cap so the
        # acquire/release/pivot contract is uniform across both adapters (FR-DUR-2/4).
        self._queue_caps: dict[str, dict[str, Any]] = {}
        self._queue_admit: dict[str, dict[str, Any]] = {}
        # Real DBOS ``Queue`` objects, kept so admission actually routes through them
        # (FR-DUR-2) rather than being created and discarded.
        self._queues: dict[str, Any] = {}
        # Registered cron-scheduled workflows (FR-DUR-3 scheduling) — kept so the
        # decorated functions stay referenced and are not garbage-collected.
        self._scheduled: dict[str, Callable[..., Any]] = {}

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
        """Create + retain a durable DBOS queue for concurrency / rate limits (FR-DUR-2).

        Returns a ``dbos.Queue`` configured with an optional global concurrency cap
        and an optional rate limiter (limit per period seconds), and STORES it so
        sandbox/LLM work is actually enqueued onto it (``enqueue``) — the real DBOS
        admission gate. The in-memory ``_queue_admit`` bookkeeping mirrors the same
        cap so the synchronous ``acquire``/``release`` contract stays uniform across
        both adapters (the shim has no Postgres-backed queue runtime).
        """
        self._ensure_launched()
        from dbos import Queue

        limiter = None
        if limiter_limit is not None and limiter_period is not None:
            limiter = {"limit": limiter_limit, "period": limiter_period}
        self._queue_caps[name] = {
            "concurrency": concurrency,
            "limiter_limit": limiter_limit,
            "limiter_period": limiter_period,
        }
        self._queue_admit[name] = {"active": set(), "waiting": deque(), "admit_times": deque()}
        queue = Queue(name, concurrency=concurrency, limiter=limiter)
        self._queues[name] = queue
        return queue

    def enqueue(self, queue_name: str, workflow_name: str, workflow_id: str, *args: Any, **kwargs: Any) -> _DbosHandle:
        """Enqueue a workflow onto a durable queue so DBOS gates admission (FR-DUR-2).

        This is the real concurrency/rate gate: DBOS only dispatches as many queued
        workflows as the queue's ``concurrency`` / rate limiter allow, and survives a
        crash. Falls back to a direct start if the queue was not created.
        """
        self._ensure_launched()
        from dbos import SetWorkflowID

        queue = self._queues.get(queue_name)
        shim = self._wf_shims.get(workflow_name)
        if shim is None:
            raise KeyError(f"workflow not registered: {workflow_name}")
        if queue is None:
            return self.start_workflow(workflow_name, workflow_id, *args, **kwargs)
        with SetWorkflowID(workflow_id):
            handle = queue.enqueue(shim, workflow_id, *args, **kwargs)
        return _DbosHandle(workflow_id, handle)

    def acquire(self, queue_name: str, work_id: str) -> bool:
        """Admit ``work_id`` onto the queue (concurrency/rate gate) (FR-DUR-2)."""
        cap = self._queue_caps.get(queue_name, {})
        st = self._queue_admit.setdefault(
            queue_name, {"active": set(), "waiting": deque(), "admit_times": deque()}
        )
        if work_id in st["active"]:
            return True
        now = time.monotonic()
        concurrency = cap.get("concurrency")
        lim, period = cap.get("limiter_limit"), cap.get("limiter_period")
        if lim is not None and period is not None:
            while st["admit_times"] and now - st["admit_times"][0] >= period:
                st["admit_times"].popleft()
        capacity_ok = concurrency is None or len(st["active"]) < concurrency
        rate_ok = lim is None or period is None or len(st["admit_times"]) < lim
        if capacity_ok and rate_ok:
            st["active"].add(work_id)
            if lim is not None:
                st["admit_times"].append(now)
            return True
        if work_id not in st["waiting"]:
            st["waiting"].append(work_id)
        return False

    def release(self, queue_name: str, work_id: str) -> str | None:
        """Free a slot and promote the next waiter — the pivot (FR-DUR-4)."""
        st = self._queue_admit.get(queue_name)
        if st is None:
            return None
        st["active"].discard(work_id)
        if st["waiting"]:
            nxt = st["waiting"][0]
            if self.acquire(queue_name, nxt):
                st["waiting"].popleft()
                return nxt
        return None

    def schedule(self, name: str, cron: str, fn: Callable[..., Any]) -> Callable[..., Any]:
        """Register + retain a cron-scheduled durable workflow (FR-DUR-3, scheduling).

        Wraps ``fn`` with ``@DBOS.scheduled(cron)`` + ``@DBOS.workflow`` so DBOS fires
        it on the schedule with crash-safe, exactly-once semantics, and STORES the
        decorated function so it stays registered for the process lifetime (the
        scheduler tick is driven this way on the DBOS path).
        """
        self._ensure_launched()
        from dbos import DBOS

        @DBOS.scheduled(cron)
        @DBOS.workflow(name=f"applicant.sched.{name}")
        def _scheduled(scheduled_time: Any, actual_time: Any) -> Any:
            return fn(scheduled_time, actual_time)

        self._scheduled[name] = _scheduled
        return _scheduled
