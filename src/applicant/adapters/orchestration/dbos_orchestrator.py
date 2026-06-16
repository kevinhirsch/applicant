"""DBOS Transact durable-orchestration adapter (FR-DUR-1/2/3).

# STAGE B — owned by Phase 0; flesh out here.

DBOS co-resides workflow/step state in the same Postgres (FR-DUR-3), giving true
mid-step resumption, durable queues (concurrency/rate-limit), and send/recv gates.
DBOS requires a live Postgres at launch, so the DEFAULT adapter is the file-backed
``CheckpointShimOrchestrator`` (keeps the test suite green); this adapter is
selected when ``ORCHESTRATOR_BACKEND=dbos`` in a real deployment.

The methods below intentionally raise ``NotImplementedError`` until Phase 0
implementers wire DBOS decorators (@DBOS.workflow / @DBOS.step / @DBOS.send/recv)
behind this port. The import of ``dbos`` is deferred so importing this module
never touches Postgres.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class DbosOrchestrator:
    """DurableOrchestrationPort backed by DBOS Transact (Phase 0 to complete)."""

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url
        self._launched = False

    def _ensure_launched(self) -> None:
        if self._launched:
            return
        # Deferred import: only touch DBOS/Postgres when actually used.
        # from dbos import DBOS, DBOSConfig  # noqa: ERA001
        raise NotImplementedError(
            "DBOS orchestrator is a Stage B (Phase 0) task; use ORCHESTRATOR_BACKEND=shim "
            "until DBOS is wired."
        )

    def register_workflow(self, name: str, fn: Callable[..., Any]) -> None:
        raise NotImplementedError("STAGE B — Phase 0: register DBOS @workflow.")

    def start_workflow(self, name: str, workflow_id: str, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("STAGE B — Phase 0: DBOS.start_workflow with idempotency key.")

    def run_step(self, workflow_id: str, step_name: str, fn: Callable[[], Any]) -> Any:
        raise NotImplementedError("STAGE B — Phase 0: wrap as a DBOS @step.")

    def send(self, workflow_id: str, topic: str, payload: Any) -> None:
        raise NotImplementedError("STAGE B — Phase 0: DBOS.send.")

    def recv(self, workflow_id: str, topic: str, timeout: float | None = None) -> Any:
        raise NotImplementedError("STAGE B — Phase 0: DBOS.recv.")

    def recover_pending(self) -> list[str]:
        raise NotImplementedError("STAGE B — Phase 0: DBOS.recover_pending_workflows.")
