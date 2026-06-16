"""File-backed durable-orchestration shim (DEFAULT adapter, FR-DUR-1/3).

# STAGE B — owned by Phase 0; the DBOS-backed adapter lives alongside this one.

This adapter implements ``DurableOrchestrationPort`` with a JSON-file checkpoint
store so it works WITHOUT a running Postgres (keeping the test suite green) while
still demonstrating *true* mid-step resumption: a completed step's result is
persisted to disk and, on a re-execution (even in a brand-new process after a
kill), that step returns its checkpointed value WITHOUT re-running its function.

For real deployments set ``ORCHESTRATOR_BACKEND=dbos`` to use the DBOS Transact
adapter (``dbos_orchestrator``), which co-resides workflow state in Postgres.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class _ShimHandle:
    workflow_id: str
    _result: Any = None

    def result(self) -> Any:
        return self._result


@dataclass
class _Queue:
    """In-process durable-queue stand-in: concurrency cap + rate limiter + pivot.

    * ``concurrency`` caps how many work-ids hold a slot at once (sandbox cap).
    * ``limiter_limit`` / ``limiter_period`` bound admissions per rolling window
      (per-provider LLM rate limit).
    * ``waiting`` is the FIFO of work that could not be admitted; ``release`` pops
      the next one (pivot-around-blocker, FR-DUR-4).
    """

    concurrency: int | None = None
    limiter_limit: int | None = None
    limiter_period: float | None = None
    active: set[str] = field(default_factory=set)
    waiting: deque[str] = field(default_factory=deque)
    admit_times: deque[float] = field(default_factory=deque)

    def _rate_ok(self, now: float) -> bool:
        if self.limiter_limit is None or self.limiter_period is None:
            return True
        # Drop admissions older than the rolling window.
        while self.admit_times and now - self.admit_times[0] >= self.limiter_period:
            self.admit_times.popleft()
        return len(self.admit_times) < self.limiter_limit

    def _capacity_ok(self) -> bool:
        return self.concurrency is None or len(self.active) < self.concurrency

    def try_admit(self, work_id: str, now: float) -> bool:
        if work_id in self.active:
            return True  # idempotent re-acquire
        if self._capacity_ok() and self._rate_ok(now):
            self.active.add(work_id)
            if self.limiter_limit is not None:
                self.admit_times.append(now)
            return True
        if work_id not in self.waiting:
            self.waiting.append(work_id)
        return False


class CheckpointShimOrchestrator:
    """Durable orchestrator backed by per-workflow JSON checkpoint files."""

    def __init__(self, checkpoint_dir: str = ".applicant_checkpoints") -> None:
        self._dir = Path(checkpoint_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._workflows: dict[str, Callable[..., Any]] = {}
        self._mailbox: dict[tuple[str, str], list[Any]] = {}
        self._queues: dict[str, _Queue] = {}

    # --- checkpoint persistence -------------------------------------------
    def _path(self, workflow_id: str) -> Path:
        safe = workflow_id.replace("/", "_")
        return self._dir / f"{safe}.checkpoint.json"

    def _load(self, workflow_id: str) -> dict[str, Any]:
        p = self._path(workflow_id)
        if p.exists():
            try:
                return json.loads(p.read_text())
            except json.JSONDecodeError:
                return {"steps": {}}
        return {"steps": {}}

    def _save(self, workflow_id: str, state: dict[str, Any]) -> None:
        p = self._path(workflow_id)
        # Atomic write so a crash mid-write never corrupts the checkpoint.
        fd, tmp = tempfile.mkstemp(dir=str(self._dir))
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(state, f)
            os.replace(tmp, p)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    # --- DurableOrchestrationPort -----------------------------------------
    def register_workflow(self, name: str, fn: Callable[..., Any]) -> None:
        self._workflows[name] = fn

    def start_workflow(self, name: str, workflow_id: str, *args: Any, **kwargs: Any) -> _ShimHandle:
        fn = self._workflows.get(name)
        if fn is None:
            raise KeyError(f"workflow not registered: {name}")
        state = self._load(workflow_id)
        state.setdefault("name", name)
        state.setdefault("steps", {})
        self._save(workflow_id, state)
        result = fn(self, workflow_id, *args, **kwargs)
        return _ShimHandle(workflow_id=workflow_id, _result=result)

    def run_step(self, workflow_id: str, step_name: str, fn: Callable[[], Any]) -> Any:
        """Run ``fn`` once; return its checkpointed result on any later re-run."""
        state = self._load(workflow_id)
        steps = state.setdefault("steps", {})
        if step_name in steps:
            # Already completed in a prior (possibly killed) execution — resume.
            return steps[step_name]
        result = fn()
        steps[step_name] = result
        self._save(workflow_id, state)
        return result

    def completed_steps(self, workflow_id: str) -> list[str]:
        """Introspection helper: which steps have checkpointed results."""
        return list(self._load(workflow_id).get("steps", {}).keys())

    def send(self, workflow_id: str, topic: str, payload: Any) -> None:
        self._mailbox.setdefault((workflow_id, topic), []).append(payload)

    def recv(self, workflow_id: str, topic: str, timeout: float | None = None) -> Any:
        box = self._mailbox.get((workflow_id, topic), [])
        return box.pop(0) if box else None

    def recover_pending(self) -> list[str]:
        """Return workflow ids that have a checkpoint file (interrupted/in-flight)."""
        return [p.stem.replace(".checkpoint", "") for p in self._dir.glob("*.checkpoint.json")]

    # --- durable queues: concurrency cap / rate limit / pivot (FR-DUR-2/4) -
    def create_queue(
        self,
        name: str,
        *,
        concurrency: int | None = None,
        limiter_limit: int | None = None,
        limiter_period: float | None = None,
    ) -> _Queue:
        q = self._queues.get(name)
        if q is None:
            q = _Queue(
                concurrency=concurrency,
                limiter_limit=limiter_limit,
                limiter_period=limiter_period,
            )
            self._queues[name] = q
        return q

    def acquire(self, queue_name: str, work_id: str) -> bool:
        """Admit ``work_id`` if capacity + rate allow; else enqueue it (FR-DUR-2)."""
        q = self._queues.get(queue_name) or self.create_queue(queue_name)
        return q.try_admit(work_id, time.monotonic())

    def release(self, queue_name: str, work_id: str) -> str | None:
        """Free ``work_id``'s slot and promote the next waiter — the pivot (FR-DUR-4)."""
        q = self._queues.get(queue_name)
        if q is None:
            return None
        q.active.discard(work_id)
        # Pivot: admit the oldest waiter that now fits (capacity yielded by the
        # blocked/awaiting application FR-AGENT-6).
        now = time.monotonic()
        while q.waiting:
            nxt = q.waiting[0]
            if q._capacity_ok() and q._rate_ok(now):
                q.waiting.popleft()
                q.active.add(nxt)
                if q.limiter_limit is not None:
                    q.admit_times.append(now)
                return nxt
            break
        return None

    def queue_state(self, queue_name: str) -> dict[str, list[str]]:
        """Introspection: active + waiting work-ids for a queue (tests/debug)."""
        q = self._queues.get(queue_name)
        if q is None:
            return {"active": [], "waiting": []}
        return {"active": sorted(q.active), "waiting": list(q.waiting)}

    def clear(self, workflow_id: str) -> None:
        """Remove a workflow's checkpoint (e.g. on terminal completion)."""
        p = self._path(workflow_id)
        if p.exists():
            p.unlink()
