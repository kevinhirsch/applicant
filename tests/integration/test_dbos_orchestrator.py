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


@skip_no_pg
def test_dbos_queue_enqueue_routes_through_real_queue():
    # FR-DUR-2: a created Queue is now RETAINED and used for admission (enqueue),
    # not created-and-discarded. The workflow runs via the durable queue runtime.
    from applicant.adapters.orchestration.dbos_orchestrator import DbosOrchestrator

    orch = DbosOrchestrator(_PG_URL)
    orch.create_queue("sandbox", concurrency=1)

    def pipeline(o, wf_id):
        return o.run_step(wf_id, "only", lambda: {"ran": True})

    orch.register_workflow("queued_pipe", pipeline)
    handle = orch.enqueue("sandbox", "queued_pipe", "wf-q-1")
    assert handle.result() == {"ran": True}
    # The Queue object was retained (proving it is no longer discarded).
    assert "sandbox" in orch._queues


@skip_no_pg
def test_dbos_schedule_registers_scheduled_workflow():
    # FR-DUR-3 scheduling: schedule() now retains the @DBOS.scheduled workflow so
    # the scheduler tick can be driven crash-safely on the DBOS path.
    from applicant.adapters.orchestration.dbos_orchestrator import DbosOrchestrator

    orch = DbosOrchestrator(_PG_URL)
    fired: list[str] = []
    orch.schedule("scheduler_tick", "* * * * *", lambda st, at: fired.append("tick"))
    assert "scheduler_tick" in orch._scheduled


@skip_no_pg
def test_dbos_backed_scheduler_tick_drives_loop():
    # NFR-247-1 / FR-DIG-1 / FR-NOTIF-2: the Scheduler tick works over the DBOS-backed
    # orchestrator end-to-end (campaign tick + digest + ladder advance).
    from datetime import UTC, datetime

    from applicant.adapters.orchestration.dbos_orchestrator import DbosOrchestrator
    from applicant.adapters.storage.in_memory import InMemoryStorage
    from applicant.application.services.agent_loop import AgentLoop
    from applicant.application.services.agent_run_service import AgentRunService
    from applicant.application.services.scheduler import Scheduler
    from applicant.core.entities.campaign import Campaign
    from applicant.core.ids import CampaignId, new_id

    orch = DbosOrchestrator(_PG_URL)
    storage = InMemoryStorage()
    cid = CampaignId(new_id())
    storage.campaigns.add(Campaign(id=cid, name="dbos-campaign"))
    loop = AgentLoop(
        storage=storage,
        agent_run_service=AgentRunService(storage),
        orchestrator=orch,
    )
    sched = Scheduler(storage=storage, agent_loop=loop)
    out = sched.tick(datetime(2026, 6, 16, tzinfo=UTC))
    assert str(cid) in out["ticked"]
