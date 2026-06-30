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

import contextlib
import errno
import hashlib
import json
import os
import tempfile
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from applicant.observability.logging import get_logger

log = get_logger(__name__)

#: Schema/integrity version stamped into every checkpoint. A file without this marker
#: (an older partial / truncated-but-parseable write) is rejected as corrupt rather
#: than trusted as complete (#218).
_CHECKPOINT_VERSION = 1


class CheckpointStorageError(OSError):
    """A durable-checkpoint write failed for a storage reason (base health signal).

    Distinct from a bare ``OSError`` so callers (the scheduler / health probe) can catch
    a *recognizable* checkpoint-storage fault instead of every IOError.
    """


class CheckpointDiskFull(CheckpointStorageError):
    """The checkpoint store is out of space (ENOSPC) — a critical health signal (#219).

    Raised in place of the raw ``OSError(28)`` so a full disk surfaces a recognizable
    event the operator can act on, instead of propagating as a generic error that drives
    an infinite step-retry loop.
    """


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
        self._queues: dict[str, _Queue] = {}
        self._scheduled: dict[str, Callable[..., Any]] = {}
        # CONC-1: per-workflow / per-queue locks serialize the non-atomic
        # ``_load -> mutate -> _save`` brackets so the 24/7 scheduler thread and the
        # request handlers can't drop each other's checkpoint writes. The registry
        # itself is guarded by ``_registry_lock``. Keyed by workflow id OR queue name.
        self._locks: dict[str, threading.Lock] = defaultdict(threading.Lock)
        self._registry_lock = threading.Lock()
        # DUR-1: load any persisted durable-queue state so a restart over the same
        # dir does not re-grant a held concurrency slot (slot leak).
        self._load_queues()

    def _lock_for(self, key: str) -> threading.Lock:
        with self._registry_lock:
            return self._locks[key]

    # --- cross-process advance guard (#220) -------------------------------
    def _lease_path(self, workflow_id: str) -> Path:
        safe = workflow_id.replace("/", "_")
        return self._dir / f"{safe}.lease"

    @contextlib.contextmanager
    def claim_workflow(self, workflow_id: str) -> Iterator[bool]:
        """Bind a parked workflow to a SINGLE advancing tick across processes (#220).

        The per-workflow ``threading.Lock`` only serializes in-process callers; two
        worker processes (e.g. a redeploy overlap, or two scheduler hosts over a shared
        checkpoint volume) could both pick up the same parked workflow and double-advance
        it. This is an OS-level exclusive lease over a per-workflow lock file: the first
        claimant yields ``True`` and holds the advance right; a concurrent claimant yields
        ``False`` and must skip the workflow this tick. The lease is released (and the
        lock file removed) when the context exits, so the next tick can re-claim it.

        Used as::

            with orch.claim_workflow(wf_id) as won:
                if won:
                    ...advance the workflow...
        """
        # threading.Lock first so in-process contenders also serialize cleanly.
        in_proc = self._lock_for(f"lease:{workflow_id}")
        if not in_proc.acquire(blocking=False):
            yield False
            return
        lease = self._lease_path(workflow_id)
        fd: int | None = None
        held = False
        try:
            try:
                # O_CREAT|O_EXCL: atomic "create-only" claim across processes.
                fd = os.open(str(lease), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.write(fd, str(os.getpid()).encode("ascii"))
                held = True
            except FileExistsError:
                held = False
            yield held
        finally:
            if fd is not None:
                with contextlib.suppress(OSError):
                    os.close(fd)
            if held:
                with contextlib.suppress(OSError):
                    lease.unlink()
            in_proc.release()

    #: Alias: a single-tick advance claim is the durable-queue "lease" primitive.
    lease = claim_workflow

    # --- checkpoint persistence -------------------------------------------
    def _path(self, workflow_id: str) -> Path:
        safe = workflow_id.replace("/", "_")
        return self._dir / f"{safe}.checkpoint.json"

    @staticmethod
    def _checksum(state: dict[str, Any]) -> str:
        """Stable integrity digest over the durable ``steps`` payload (#218).

        Computed over a canonical JSON encoding of ``steps`` (sorted keys) so a
        truncated/partial file whose stamped digest no longer matches its content — or
        which carries no digest at all — is detectable as corrupt rather than trusted.
        """
        steps = state.get("steps", {})
        canonical = json.dumps(steps, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def verify_checkpoint(self, workflow_id: str) -> bool:
        """Return whether the on-disk checkpoint for ``workflow_id`` is intact (#218).

        ``True`` only when the file parses, carries the version + integrity markers, and
        the stored digest matches a fresh checksum of its steps. A truncated-but-parseable
        write (no/old marker, or a digest mismatch) returns ``False`` and is treated as
        "no checkpoint" by ``_load`` so the step re-executes instead of returning stale
        or partial data.
        """
        p = self._path(workflow_id)
        if not p.exists():
            return False
        try:
            state = json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            return False
        return self._is_intact(state)

    @staticmethod
    def _is_intact(state: Any) -> bool:
        if not isinstance(state, dict):
            return False
        if state.get("_version") != _CHECKPOINT_VERSION:
            return False
        stored = state.get("_integrity")
        if not isinstance(stored, str):
            return False
        return stored == CheckpointShimOrchestrator._checksum(state)

    def _load(self, workflow_id: str) -> dict[str, Any]:
        p = self._path(workflow_id)
        if p.exists():
            try:
                raw = p.read_text()
                state = json.loads(raw)
            except json.JSONDecodeError:
                # Unparseable checkpoint: log and treat as "no checkpoint" so the step
                # re-executes from scratch (transparent recovery, #218). Raising here
                # would prevent any recovery; returning empty state lets the workflow
                # restart cleanly. The warning surfaces the event for operators.
                log.warning(
                    "checkpoint_corrupted_treating_as_empty",
                    workflow_id=workflow_id,
                    path=str(p),
                )
                return {"steps": {}}
            except OSError as exc:
                raise OSError(
                    f"Failed to read checkpoint for workflow {workflow_id!r} from {p}: {exc}. "
                    "The disk may have failed or the file may be inaccessible."
                ) from exc
            # #218: a structurally-valid-but-partial file (missing/mismatched integrity
            # marker) is a truncated write, NOT a complete checkpoint — reject it as
            # corrupt so the step re-runs rather than trusting stale/partial data.
            if not self._is_intact(state):
                log.warning(
                    "checkpoint_integrity_failed_treating_as_empty",
                    workflow_id=workflow_id,
                    path=str(p),
                )
                return {"steps": {}}
            return state
        return {"steps": {}}

    def _save(self, workflow_id: str, state: dict[str, Any]) -> None:
        p = self._path(workflow_id)
        # Stamp the integrity markers so a later load can tell a complete checkpoint from
        # a truncated-but-parseable one (#218).
        state["_version"] = _CHECKPOINT_VERSION
        state["_integrity"] = self._checksum(state)
        # Atomically write so a crash mid-write never corrupts the checkpoint.
        # Check for disk-full / write failure before writing the final checkpoint.
        try:
            fd, tmp = tempfile.mkstemp(dir=str(self._dir))
        except OSError as exc:
            raise self._storage_error(exc, workflow_id, p, creating_temp=True) from exc
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(state, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, p)
        except OSError as exc:
            raise self._storage_error(exc, workflow_id, p, creating_temp=False) from exc
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    @staticmethod
    def _storage_error(
        exc: OSError, workflow_id: str, path: Path, *, creating_temp: bool
    ) -> CheckpointStorageError:
        """Map a raw write ``OSError`` to a recognizable checkpoint health signal (#219).

        ENOSPC becomes ``CheckpointDiskFull`` so the scheduler/health layer can react to
        a full disk instead of letting a generic error drive an infinite retry loop; any
        other write failure becomes the ``CheckpointStorageError`` base.
        """
        where = (
            f"Cannot create temporary checkpoint file for workflow {workflow_id!r} in "
            f"{path.parent}"
            if creating_temp
            else f"Failed to write checkpoint for workflow {workflow_id!r} to {path}"
        )
        if exc.errno == errno.ENOSPC:
            return CheckpointDiskFull(
                exc.errno,
                f"{where}: no space left on device. The checkpoint store is full.",
            )
        return CheckpointStorageError(
            exc.errno or errno.EIO,
            f"{where}: {exc}. The disk may be full or the filesystem is read-only.",
        )

    # --- DurableOrchestrationPort -----------------------------------------
    def register_workflow(self, name: str, fn: Callable[..., Any]) -> None:
        self._workflows[name] = fn

    def start_workflow(self, name: str, workflow_id: str, *args: Any, **kwargs: Any) -> _ShimHandle:
        fn = self._workflows.get(name)
        if fn is None:
            raise KeyError(f"workflow not registered: {name}")
        with self._lock_for(workflow_id):
            state = self._load(workflow_id)
            state.setdefault("name", name)
            state.setdefault("steps", {})
            self._save(workflow_id, state)
        result = fn(self, workflow_id, *args, **kwargs)
        return _ShimHandle(workflow_id=workflow_id, _result=result)

    def run_step(self, workflow_id: str, step_name: str, fn: Callable[[], Any]) -> Any:
        """Run ``fn`` once; return its checkpointed result on any later re-run.

        CONC-1: the ``_load -> mutate -> _save`` bracket is guarded by the
        per-workflow lock so concurrent steps (scheduler thread vs. request handler)
        cannot read-modify-write over each other and drop checkpoints.
        """
        with self._lock_for(workflow_id):
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
        """Durably enqueue a message for ``(workflow_id, topic)`` (FR-DUR-1/3).

        The mailbox is persisted into the workflow's checkpoint file (under
        ``state["mailbox"][topic]``) so a decision sent BEFORE a crash/restart is
        not lost: a fresh ``CheckpointShimOrchestrator`` over the same directory can
        ``recv`` it. This makes the approval gate survive a mid-step restart, which
        the previous in-process dict could not.
        """
        with self._lock_for(workflow_id):
            state = self._load(workflow_id)
            mailbox = state.setdefault("mailbox", {})
            mailbox.setdefault(topic, []).append(payload)
            self._save(workflow_id, state)

    def recv(self, workflow_id: str, topic: str, timeout: float | None = None) -> Any:
        """Pop the oldest durably-stored message for ``(workflow_id, topic)``.

        Returns immediately (callers poll/await across ticks). The popped payload is
        removed from the persisted mailbox and the checkpoint is re-saved, so a
        decision is delivered exactly once even across restarts.
        """
        with self._lock_for(workflow_id):
            state = self._load(workflow_id)
            mailbox = state.get("mailbox", {})
            box = mailbox.get(topic, [])
            if not box:
                return None
            payload = box.pop(0)
            if not box:
                mailbox.pop(topic, None)
            state["mailbox"] = mailbox
            self._save(workflow_id, state)
            return payload

    #: The pipeline's final checkpointed step — its presence in a checkpoint means the
    #: workflow ran to its terminal ``done`` state and must NOT be re-driven (DUR-2).
    _TERMINAL_STEP = "teardown"

    def recover_pending(self) -> list[str]:
        """Return workflow ids with an *interrupted* checkpoint (DUR-2).

        Terminal/done checkpoints are skipped: a workflow that reached its terminal
        step (``teardown``) is complete, so re-driving it every boot would re-run the
        whole pipeline (duplicate OutcomeEvent / re-notify). ``clear`` normally removes
        a done workflow's checkpoint; this is the defense-in-depth filter for any that
        linger (e.g. a crash between the terminal step and ``clear``).
        """
        pending: list[str] = []
        for p in self._dir.glob("*.checkpoint.json"):
            wf_id = p.stem.replace(".checkpoint", "")
            try:
                state = json.loads(p.read_text())
            except json.JSONDecodeError:
                log.warning(
                    "checkpoint_corrupted_skipped",
                    workflow_id=wf_id,
                    path=str(p),
                )
                continue
            except OSError as exc:
                log.warning(
                    "checkpoint_read_failed_skipped",
                    workflow_id=wf_id,
                    path=str(p),
                    error=str(exc),
                )
                continue
            steps = state.get("steps", {})
            if self._TERMINAL_STEP in steps or state.get("terminal"):
                continue
            pending.append(wf_id)
        return pending

    # --- durable queues: concurrency cap / rate limit / pivot (FR-DUR-2/4) -
    def create_queue(
        self,
        name: str,
        *,
        concurrency: int | None = None,
        limiter_limit: int | None = None,
        limiter_period: float | None = None,
    ) -> _Queue:
        with self._lock_for(f"queue:{name}"):
            q = self._queues.get(name)
            if q is None:
                q = _Queue(
                    concurrency=concurrency,
                    limiter_limit=limiter_limit,
                    limiter_period=limiter_period,
                )
                self._queues[name] = q
                self._save_queue(name, q)
            return q

    def acquire(self, queue_name: str, work_id: str) -> bool:
        """Admit ``work_id`` if capacity + rate allow; else enqueue it (FR-DUR-2)."""
        with self._lock_for(f"queue:{queue_name}"):
            q = self._queues.get(queue_name)
            if q is None:
                q = _Queue()
                self._queues[queue_name] = q
            admitted = q.try_admit(work_id, time.monotonic())
            # DUR-1: persist active/waiting so a restart over the same dir does not
            # re-grant a slot the cap already handed out (slot leak).
            self._save_queue(queue_name, q)
            return admitted

    def release(self, queue_name: str, work_id: str) -> str | None:
        """Free ``work_id``'s slot and promote the next waiter — the pivot (FR-DUR-4)."""
        with self._lock_for(f"queue:{queue_name}"):
            q = self._queues.get(queue_name)
            if q is None:
                return None
            q.active.discard(work_id)
            # PIVOT (FR-DUR-4): promote the FIRST waiter that currently fits — not
            # only the head. The previous ``while ... break`` only ever inspected
            # the head, so a head that cannot be admitted (e.g. its own per-item
            # rate window is exhausted, or it is a stale already-active duplicate)
            # stalled a later admissible waiter. Scan the FIFO in order and admit
            # the first one that fits.
            now = time.monotonic()
            promoted = self._promote_first_fitting(q, now)
            self._save_queue(queue_name, q)
            return promoted

    @staticmethod
    def _promote_first_fitting(q: _Queue, now: float) -> str | None:
        """Admit the first waiter that currently fits; return it (or ``None``)."""
        for idx in range(len(q.waiting)):
            nxt = q.waiting[idx]
            if nxt in q.active:
                # Stale already-admitted duplicate: drop it and keep scanning so a
                # genuine waiter behind it is not blocked.
                del q.waiting[idx]
                return nxt
            if q._capacity_ok() and q._rate_ok(now):
                del q.waiting[idx]
                q.active.add(nxt)
                if q.limiter_limit is not None:
                    q.admit_times.append(now)
                return nxt
        return None

    # --- durable-queue persistence (DUR-1) --------------------------------
    def _queues_path(self) -> Path:
        return self._dir / "_queues.json"

    def _save_queue(self, name: str, q: _Queue) -> None:
        """Persist all queues' admit/wait state so slots survive a restart (DUR-1).

        ``admit_times`` (the rolling rate-limit window) uses ``time.monotonic`` which
        is not portable across processes, so it is intentionally NOT persisted — only
        the durable ``active`` set + ``waiting`` FIFO + caps are, which is what guards
        the concurrency slot against re-grant.
        """
        data: dict[str, Any] = {}
        for qname, queue in self._queues.items():
            data[qname] = {
                "concurrency": queue.concurrency,
                "limiter_limit": queue.limiter_limit,
                "limiter_period": queue.limiter_period,
                "active": sorted(queue.active),
                "waiting": list(queue.waiting),
            }
        p = self._queues_path()
        try:
            fd, tmp = tempfile.mkstemp(dir=str(self._dir))
        except OSError as exc:
            raise OSError(
                f"Cannot create temporary queue file in {self._dir}: {exc}. "
                "Check disk space and permissions."
            ) from exc
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, p)
        except OSError as exc:
            raise OSError(
                f"Failed to write queue state to {p}: {exc}. "
                "The disk may be full or the filesystem is read-only."
            ) from exc
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def _load_queues(self) -> None:
        """Rehydrate durable-queue state on startup (DUR-1)."""
        p = self._queues_path()
        if not p.exists():
            return
        try:
            data = json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            return
        for name, qd in data.items():
            self._queues[name] = _Queue(
                concurrency=qd.get("concurrency"),
                limiter_limit=qd.get("limiter_limit"),
                limiter_period=qd.get("limiter_period"),
                active=set(qd.get("active", [])),
                waiting=deque(qd.get("waiting", [])),
            )

    def enqueue(
        self, queue_name: str, workflow_name: str, workflow_id: str, *args: Any, **kwargs: Any
    ) -> _ShimHandle:
        """Admit onto the queue, then start the workflow (uniform with DBOS enqueue).

        On the shim there is no separate dispatcher, so admission is synchronous via
        ``acquire`` and the workflow runs inline; on DBOS ``enqueue`` defers dispatch
        to the durable queue runtime (FR-DUR-2).
        """
        self.acquire(queue_name, workflow_id)
        return self.start_workflow(workflow_name, workflow_id, *args, **kwargs)

    def schedule(self, name: str, cron: str, fn: Callable[..., Any]) -> Callable[..., Any]:
        """Register a cron-scheduled function (FR-DUR-3 scheduling).

        The shim has no cron runtime — the asyncio scheduler task in ``app/lifespan``
        drives the cadence instead — so this records the function and returns it so
        the call site is uniform across both adapters.
        """
        self._scheduled[name] = fn
        return fn

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
