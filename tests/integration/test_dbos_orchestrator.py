"""DBOS-backed durable orchestrator integration (FR-DUR-1/2/3).

DBOS requires a live Postgres, so this whole module is skipped unless
``ORCHESTRATOR_BACKEND=dbos`` AND ``DATABASE_URL`` point at a reachable Postgres.
The default test lane (no Postgres) runs the file-backed shim instead, which has
its own resumption test in ``test_durable_workflow.py``.

To run locally:
    ORCHESTRATOR_BACKEND=dbos DATABASE_URL=postgresql://... \\
        uv run pytest -m integration tests/integration/test_dbos_orchestrator.py
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.integration

_PG_URL = os.getenv("DATABASE_URL", "")
_DBOS_ENABLED = os.getenv("ORCHESTRATOR_BACKEND") == "dbos" and _PG_URL.startswith(
    ("postgres://", "postgresql://", "postgresql+psycopg://")
)

skip_no_pg = pytest.mark.skipif(
    not _DBOS_ENABLED,
    reason="DBOS needs a live Postgres; set ORCHESTRATOR_BACKEND=dbos + DATABASE_URL.",
)


@skip_no_pg
def test_dbos_workflow_resumes_from_checkpoint():
    from applicant.adapters.orchestration.dbos_orchestrator import DbosOrchestrator

    orch = DbosOrchestrator(_PG_URL)
    side: list[str] = []

    def pipeline(o, wf_id):
        o.run_step(wf_id, "step_one", lambda: side.append("one") or {"value": 1})
        o.run_step(wf_id, "step_two", lambda: side.append("two") or {"value": 2})
        return {"done": True}

    orch.register_workflow("dbos_pipe", pipeline)
    handle = orch.start_workflow("dbos_pipe", "wf-dbos-1")
    assert handle.result()["done"] is True

    # Re-run the same workflow id: completed steps must not re-execute.
    side.clear()
    handle2 = orch.start_workflow("dbos_pipe", "wf-dbos-1")
    handle2.result()
    assert side == []  # both steps were checkpointed


@skip_no_pg
def test_dbos_send_recv_roundtrip():
    from applicant.adapters.orchestration.dbos_orchestrator import DbosOrchestrator

    orch = DbosOrchestrator(_PG_URL)

    def gated(o, wf_id):
        return o.recv(wf_id, "approval", timeout=10.0)

    orch.register_workflow("gated", gated)
    handle = orch.start_workflow("gated", "wf-gate-1")
    orch.send("wf-gate-1", "approval", {"approved": True})
    assert handle.result() == {"approved": True}


@skip_no_pg
def test_dbos_queue_concurrency_cap_and_pivot():
    # FR-DUR-2/4: concurrency cap + pivot-around-blocker on the DBOS-backed adapter.
    from applicant.adapters.orchestration.dbos_orchestrator import DbosOrchestrator

    orch = DbosOrchestrator(_PG_URL)
    orch.create_queue("sandbox", concurrency=2)
    assert orch.acquire("sandbox", "app-1") is True
    assert orch.acquire("sandbox", "app-2") is True
    assert orch.acquire("sandbox", "app-3") is False
    assert orch.release("sandbox", "app-1") == "app-3"  # waiter pivots in
