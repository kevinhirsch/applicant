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

import threading
import time
from collections import deque
from collections.abc import Callable
from typing import Any

#: "Effectively forever" wait for the approval gate (FR-DUR-3). DBOS ``recv``
#: requires a numeric timeout, so a very large finite value stands in for an
#: indefinite wait without spuriously timing out a pending approval (~10 years).
_INDEFINITE_WAIT_SECONDS = 315_360_000.0


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

    def __init__(
        self,
        database_url: str,
        approval_timeout_seconds: float = 2_592_000.0,
        live_approval_timeout_seconds: Callable[[], float | None] | None = None,
    ) -> None:
        self._database_url = database_url
        #: How long the engine waits for a human decision (FR-DUR-3). Default 30
        #: days (2,592,000 seconds); 0 means effectively forever (fallback to the
        #: old hardcoded ~10-year constant). This is only the ``settings.
        #: approval_timeout_days``/``approval_wait_seconds`` env default, latched
        #: ONCE when the container builds this orchestrator — used as the fallback
        #: when ``live_approval_timeout_seconds`` is absent or has nothing saved.
        self._approval_timeout_seconds = approval_timeout_seconds
        # Lens 11 #23: optional live re-read of the operator's persisted Settings >
        # Automation override (``SetupService.set_automation_prefs(
        # approval_timeout_days=..., approval_wait_seconds=...)``), consulted on
        # EVERY ``recv`` call instead of only the constructor-time snapshot above —
        # so a Settings change actually governs how long a pending final-approval
        # waits before timing out, without a process restart. ``None`` (legacy/unit
        # construction without a container) means no live source is wired; behavior
        # is then byte-identical to before (the constructor value only).
        self._live_approval_timeout_seconds = live_approval_timeout_seconds
        self._configured = False
        self._launched = False
        self._dbos: Any = None
        self._workflows: dict[str, Callable[..., Any]] = {}
        self._wf_shims: dict[str, Callable[..., Any]] = {}
        # Admission bookkeeping mirrors the DBOS queue concurrency cap so the
        # acquire/release/pivot contract is uniform across both adapters (FR-DUR-2/4).
        self._queue_caps: dict[str, dict[str, Any]] = {}
        self._queue_admit: dict[str, dict[str, Any]] = {}
        # CONC-DBOS-1: ``CapacityService`` is shared across the scheduler thread +
        # request threads, so the non-atomic admission bookkeeping (active/waiting/
        # admit_times) must be serialized. Mirror the shim's per-key locking with a
        # single lock guarding create_queue / acquire / release.
        self._admit_lock = threading.Lock()
        # Real DBOS ``Queue`` objects, kept so admission actually routes through them
        # (FR-DUR-2) rather than being created and discarded.
        self._queues: dict[str, Any] = {}
        # Registered cron-scheduled workflows (FR-DUR-3 scheduling) — kept so the
        # decorated functions stay referenced and are not garbage-collected.
        self._scheduled: dict[str, Callable[..., Any]] = {}

    def _ensure_configured(self) -> None:
        """CONFIGURE phase: instantiate DBOS so decorators register (NO launch yet).

        Registration (``@DBOS.workflow`` / ``@DBOS.scheduled`` / ``Queue(...)``) MUST
        happen before ``DBOS.launch()`` or queues are never dispatched and workflows
        are not recovered. So configuration (creating the singleton + applying the
        decorators) is split from launching: register* / create_queue / schedule run
        here without launching; only the execution methods (start/enqueue/send/recv/
        run_step/recover) actually ``launch()`` via :meth:`_ensure_launched`.
        """
        if self._configured:
            return
        # Deferred import: only touch DBOS / Postgres when actually used.
        from dbos import DBOS, DBOSConfig

        config: DBOSConfig = {
            "name": "applicant",
            "database_url": self._database_url,
        }
        DBOS(config=config)
        self._dbos = DBOS
        self._configured = True

    def _ensure_launched(self) -> None:
        """LAUNCH phase: launch DBOS exactly once, AFTER everything is registered.

        DBOS recovers pending workflows automatically at ``launch()``, so this is the
        single transition from the configure phase to a running runtime.
        """
        if self._launched:
            return
        self._ensure_configured()
        self._dbos.launch()
        self._launched = True

    def register_workflow(self, name: str, fn: Callable[..., Any]) -> None:
        """Register ``fn`` as a DBOS durable workflow under ``name`` (FR-DUR-1).

        CONFIGURE-only: applies the ``@DBOS.workflow`` decorator (which requires the
        DBOS singleton to exist) but does NOT launch — so multiple workflows can be
        registered before the single ``launch()``.
        """
        self._ensure_configured()
        DBOS = self._dbos

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
        from dbos import SetWorkflowID

        shim = self._wf_shims.get(name)
        if shim is None:
            raise KeyError(f"workflow not registered: {name}")
        with SetWorkflowID(workflow_id):
            handle = self._dbos.start_workflow(shim, workflow_id, *args, **kwargs)
        return _DbosHandle(workflow_id, handle)

    def run_step(self, workflow_id: str, step_name: str, fn: Callable[[], Any]) -> Any:
        """Run an idempotent, checkpointed DBOS step (mid-step resumption).

        Real DBOS ``run_step`` takes STEP OPTIONS then the function:
        ``DBOS.run_step({"name": ...}, fn)`` (the old ``run_step(fn, name=...)`` was
        the wrong signature). The step is KEYED by ``(workflow_id, step_name)`` so two
        concurrent applications reusing fixed step names ("prefill"/"submit") do NOT
        collide on the same checkpoint key.
        """
        self._ensure_launched()
        DBOS = self._dbos

        # Distinct, deterministic key per workflow so identical step names across
        # concurrent workflows checkpoint independently.
        step_key = f"{workflow_id}:{step_name}"
        return DBOS.run_step({"name": step_key}, fn)

    def send(self, workflow_id: str, topic: str, payload: Any) -> None:
        """Deliver an approval-gate message to a waiting workflow (FR-DUR-3)."""
        self._ensure_launched()
        self._dbos.send(workflow_id, payload, topic=topic)

    def _resolve_timeout_seconds(self, timeout: float | None) -> float:
        """Compute the effective ``recv`` timeout (lens 11 #23: live-configurable).

        An explicit per-call ``timeout`` always wins (unchanged behavior). Otherwise,
        re-reads ``live_approval_timeout_seconds()`` (the persisted Settings >
        Automation override) FIRST — falling back to the constructor-time
        ``approval_timeout_seconds`` snapshot only when the live source is absent or
        has nothing saved — so a Settings change takes effect on the very next
        ``recv`` without a process restart. A non-positive effective value means
        "wait indefinitely" (mirrors the pre-existing 0-means-forever contract).
        Pulled out of ``recv`` so it can be unit-tested without a real DBOS runtime.
        """
        if timeout is not None:
            return timeout
        live: float | None = None
        if self._live_approval_timeout_seconds is not None:
            try:
                live = self._live_approval_timeout_seconds()
            except Exception:  # pragma: no cover - defensive: never break a recv
                live = None
        effective = live if live is not None else self._approval_timeout_seconds
        return effective if effective > 0 else _INDEFINITE_WAIT_SECONDS

    def recv(self, workflow_id: str, topic: str, timeout: float | None = None) -> Any:
        """Durably wait for a message on ``topic`` (survives a crash).

        ``timeout=None`` means wait per the configured approval-gate timeout (the old
        code silently substituted 60s, so an approval-gate wait would spuriously time
        out) — live-re-read every call (lens 11 #23) rather than latched once at
        container-build time. A very large finite timeout stands in for "effectively
        forever" since DBOS ``recv`` requires a numeric ``timeout_seconds``.
        """
        self._ensure_launched()
        DBOS = self._dbos

        timeout_seconds = self._resolve_timeout_seconds(timeout)
        return DBOS.recv(topic=topic, timeout_seconds=timeout_seconds)

    def recover_pending(self) -> list[str]:
        """Resume interrupted workflows on startup; return their ids (FR-DUR-1).

        DBOS 2.x has NO ``recover_pending_workflows()`` — calling it AttributeErrors
        on the real path. DBOS recovers pending workflows AUTOMATICALLY at
        ``launch()``, so recovery is implicit: ensure we are launched and return ``[]``
        (recovery has already been kicked off by the runtime).
        """
        self._ensure_launched()
        return []

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

        CONFIGURE-only: ``Queue(...)`` MUST be created before ``launch()`` or DBOS
        never dispatches it. So this only configures (no launch).
        """
        self._ensure_configured()
        from dbos import Queue

        limiter = None
        if limiter_limit is not None and limiter_period is not None:
            limiter = {"limit": limiter_limit, "period": limiter_period}
        # CONC-DBOS-1: guard the shared admission bookkeeping mutation.
        with self._admit_lock:
            self._queue_caps[name] = {
                "concurrency": concurrency,
                "limiter_limit": limiter_limit,
                "limiter_period": limiter_period,
            }
            self._queue_admit[name] = {
                "active": set(),
                "waiting": deque(),
                "admit_times": deque(),
            }
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
        """Admit ``work_id`` onto the queue (concurrency/rate gate) (FR-DUR-2).

        CONC-DBOS-1: guarded by ``_admit_lock`` so the scheduler + request threads
        sharing this adapter cannot read-modify-write the admission state over each
        other (lost/double admissions).
        """
        with self._admit_lock:
            return self._acquire_locked(queue_name, work_id)

    def _acquire_locked(self, queue_name: str, work_id: str) -> bool:
        """``acquire`` body; caller MUST already hold ``_admit_lock``."""
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
        """Free a slot and promote the next fitting waiter — the pivot (FR-DUR-4).

        CONC-DBOS-1: guarded by ``_admit_lock``. PIVOT: promote the FIRST waiter
        that currently fits (scanning the FIFO), not only the head — a rate-blocked
        head must not stall a later admissible waiter (pivot-around-blocker).
        """
        with self._admit_lock:
            st = self._queue_admit.get(queue_name)
            if st is None:
                return None
            st["active"].discard(work_id)
            waiting = st["waiting"]
            for idx in range(len(waiting)):
                nxt = waiting[idx]
                if nxt in st["active"]:
                    # Stale already-admitted duplicate: drop it and keep scanning so
                    # a genuine waiter behind it is not blocked.
                    del waiting[idx]
                    return nxt
                if self._acquire_locked(queue_name, nxt):
                    # _acquire_locked appended a NEW waiting entry only if it could
                    # not admit; here it admitted, so remove the original position.
                    del waiting[idx]
                    return nxt
            return None

    def schedule(self, name: str, cron: str, fn: Callable[..., Any]) -> Callable[..., Any]:
        """Register + retain a cron-scheduled durable workflow (FR-DUR-3, scheduling).

        Wraps ``fn`` with ``@DBOS.scheduled(cron)`` + ``@DBOS.workflow`` so DBOS fires
        it on the schedule with crash-safe, exactly-once semantics, and STORES the
        decorated function so it stays registered for the process lifetime (the
        scheduler tick is driven this way on the DBOS path).

        CONFIGURE-only: ``@DBOS.scheduled`` MUST register before ``launch()`` or the
        schedule never fires. So this only configures (no launch).
        """
        self._ensure_configured()
        DBOS = self._dbos

        @DBOS.scheduled(cron)
        @DBOS.workflow(name=f"applicant.sched.{name}")
        def _scheduled(scheduled_time: Any, actual_time: Any) -> Any:
            return fn(scheduled_time, actual_time)

        self._scheduled[name] = _scheduled
        return _scheduled
