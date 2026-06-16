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
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class _ShimHandle:
    workflow_id: str
    _result: Any = None

    def result(self) -> Any:
        return self._result


class CheckpointShimOrchestrator:
    """Durable orchestrator backed by per-workflow JSON checkpoint files."""

    def __init__(self, checkpoint_dir: str = ".applicant_checkpoints") -> None:
        self._dir = Path(checkpoint_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._workflows: dict[str, Callable[..., Any]] = {}
        self._mailbox: dict[tuple[str, str], list[Any]] = {}

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

    def clear(self, workflow_id: str) -> None:
        """Remove a workflow's checkpoint (e.g. on terminal completion)."""
        p = self._path(workflow_id)
        if p.exists():
            p.unlink()
