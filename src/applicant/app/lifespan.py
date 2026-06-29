"""App lifespan: startup recovers + re-drives durable workflows, seeds dormant
surfaces, and (when enabled) starts the scheduler background loop; shutdown stops
the loop + disposes the engine. DB connectivity is verified but tolerated absent
(so tests/first-boot work) (FR-DUR-1, FR-DIG-1, FR-NOTIF-2, FR-UI-2, NFR-247-1).
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI

from applicant.application.workflows.application_pipeline import WORKFLOW_NAME
from applicant.dormant import seed_dormant_surfaces
from applicant.observability.logging import get_logger

log = get_logger(__name__)


def _redrive_pending(container) -> int:
    """Re-drive every recovered pending workflow so a killed worker resumes (FR-DUR-1).

    ``recover_pending`` returns interrupted workflow ids; on the shim it only lists
    them, so here we actually re-start each (idempotent — completed steps return
    their checkpointed result without re-running). On DBOS recovery is automatic,
    so this is a best-effort no-op there.

    Crucially, recovery rebuilds a LIVE ``PipelineContext`` per recovered application
    via the agent loop (FR-DUR-1/FR-LOG-1/4): re-starting with no context would let a
    recovered+approved application reach ``_submit`` with no submission service and
    silently drop the real outcome (no OutcomeEvent, no terminal §7 state, no
    teardown). The agent loop binds the same services used for fresh runs.
    """
    orch = container.orchestrator
    loop = getattr(container, "agent_loop", None)
    recovered = orch.recover_pending()
    redriven = 0
    for wf_id in recovered:
        try:
            if loop is not None:
                loop.redrive_recovered(wf_id)
            else:  # pragma: no cover - loop is always wired in the container
                orch.start_workflow(WORKFLOW_NAME, wf_id)
            redriven += 1
        except Exception as exc:  # pragma: no cover - defensive (already-running etc.)
            log.info("redrive_skipped", workflow_id=wf_id, reason=str(exc))
    return redriven


async def _scheduler_loop(container) -> None:
    """Periodically tick the scheduler (FR-DIG-1, FR-NOTIF-2, NFR-247-1).

    Started ONLY when ``SCHEDULER_ENABLED`` so the default test lane / TestClient
    never spins a live loop. The tick itself is pure (injected clock); the sleep
    here is the only timing element and lives outside the hermetic unit lane.
    """
    interval = container.settings.scheduler_interval_seconds
    while True:
        try:
            # ROBUST: the tick is fully synchronous and long-blocking (sync DB,
            # runs whole pipelines inline via ``start_workflow(...).result()``,
            # notifications). Running it directly on the event loop blocks ALL HTTP
            # handling for the tick's duration, so run it off the loop in a worker
            # thread. The scheduler builds a fresh per-tick storage/session
            # (``tick_services_factory``) and guards each campaign with a
            # per-campaign lock, so moving off-loop corrupts no non-thread-safe state.
            await asyncio.to_thread(container.scheduler.tick, datetime.now(UTC))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("scheduler_tick_error", error=str(exc))
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(app: FastAPI):
    container = app.state.container
    scheduler_task: asyncio.Task | None = None

    # 1) Recover + RE-DRIVE interrupted durable workflows (FR-DUR-1).
    try:
        redriven = _redrive_pending(container)
        log.info("durable_recovery", redriven=redriven)
    except NotImplementedError:
        log.info("durable_recovery_skipped", reason="orchestrator backend not ready")
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("durable_recovery_failed", error=str(exc))

    # 2) Verify DB connectivity (tolerate no-DB in tests).
    try:
        healthy = container.storage.healthcheck()
        log.info("db_healthcheck", healthy=healthy)
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("db_healthcheck_failed", error=str(exc))

    # 3) Register dormant surfaces (FR-UI-2). Tolerate no-DB.
    try:
        session = getattr(container.storage, "_session", None)
        count = seed_dormant_surfaces(session)
        if session is not None:
            container.storage.commit()
        log.info("dormant_surfaces_seeded", count=count)
    except Exception as exc:  # pragma: no cover - defensive
        # Roll back so a failed seed doesn't leave the shared boot Session in an
        # aborted-transaction state that makes every later query (ensure_system_campaign,
        # request handlers) fail with InFailedSqlTransaction on a real Postgres.
        try:
            container.storage.rollback()
        except Exception:
            pass
        log.warning("dormant_seed_failed", error=str(exc))

    # 3b) Seed the reserved system campaign so instance-level secrets (the LLM key,
    #     sandbox tokens) can be sealed in the credential store, whose campaign_id is
    #     a non-null FK to campaigns. Only on a real DB — in-memory storage has no FK,
    #     and skipping keeps the hermetic test lane's campaign listings clean. Kept
    #     inactive so the scheduler never runs it; excluded from campaign listings.
    try:
        from applicant.app.container import ensure_system_campaign

        if ensure_system_campaign(container.storage):
            log.info("system_campaign_seeded")
    except Exception as exc:  # pragma: no cover - tolerate first-boot races
        log.warning("system_campaign_seed_failed", error=str(exc))

    # 4) Start the scheduler loop ONLY when enabled (default OFF, hermetic safety).
    if getattr(container.settings, "scheduler_enabled", False) and container.scheduler is not None:
        scheduler_task = asyncio.create_task(_scheduler_loop(container))
        log.info("scheduler_started", interval=container.settings.scheduler_interval_seconds)
    else:
        log.info("scheduler_disabled")

    yield

    # Shutdown: stop the scheduler loop, then dispose the engine if present.
    if scheduler_task is not None:
        scheduler_task.cancel()
        try:
            await scheduler_task
        except asyncio.CancelledError:  # pragma: no cover - shutdown (expected)
            pass
        except Exception as exc:  # pragma: no cover - shutdown
            # Don't silently swallow the scheduler's final exception — log it so a
            # crash on the last tick is visible in shutdown diagnostics.
            log.warning("scheduler_stop_error", error=str(exc))
        log.info("scheduler_stopped")
    if getattr(container, "engine", None) is not None:
        container.engine.dispose()
        log.info("engine_disposed")
