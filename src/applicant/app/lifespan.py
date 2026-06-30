"""App lifespan: startup recovers + re-drives durable workflows, seeds dormant
surfaces, and (when enabled) starts the scheduler background loop; shutdown stops
the loop + flushes checkpoints + cleans up sandboxes + disposes the engine.
DB connectivity is verified but tolerated absent (so tests/first-boot work)
(FR-DUR-1, FR-DIG-1, FR-NOTIF-2, FR-UI-2, NFR-247-1).
"""

from __future__ import annotations

import asyncio
import signal
import sys
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI

from applicant.application.workflows.application_pipeline import WORKFLOW_NAME
from applicant.dormant import seed_dormant_surfaces
from applicant.observability.capabilities import capability_status
from applicant.observability.logging import get_logger

log = get_logger(__name__)

#: Set by the signal handler on SIGTERM/SIGINT so the scheduler loop and other
#: async tasks can check whether shutdown was requested.
_shutdown_requested: bool = False


def _handle_signal(sig: int, frame: Any) -> None:
    """Signal handler for graceful shutdown (FR-DUR-1, #316).

    Sets a flag that the scheduler loop and other async tasks can observe to
    stop cleanly. On the second SIGTERM/SIGINT (hard kill), exit immediately.
    """
    global _shutdown_requested
    if _shutdown_requested:
        log.warning("graceful_shutdown_forced", signal=sig)
        sys.exit(1)
    _shutdown_requested = True
    signame = signal.Signals(sig).name
    log.info("graceful_shutdown_requested", signal=signame)


def _register_shutdown_signals() -> None:
    """Register signal handlers for graceful shutdown."""
    for s in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(s, _handle_signal)
        except (ValueError, OSError):
            # Not running on the main thread, or signals not supported (e.g. Windows
            # subprocess). Either way, graceful shutdown degrades to the lifespan
            # shutdown path, which still runs.
            pass


def _flush_checkpoints(container: Any) -> None:
    """Flush any in-memory checkpoint state to disk (FR-DUR-1, #316).

    The checkpoint shim persists on every write, so this is a no-op there.
    On DBOS the runtime handles its own flush. Defensive logging ensures
    we surface any unexpected failures.
    """
    orch = getattr(container, "orchestrator", None)
    if orch is None:
        return
    try:
        flush = getattr(orch, "flush", None)
        if flush is not None:
            flush()
            log.info("checkpoint_flush_completed")
        else:
            log.info("checkpoint_flush_skipped", reason="orchestrator has no flush method")
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("checkpoint_flush_failed", error=str(exc))


def _cleanup_sandboxes(container: Any) -> None:
    """Tear down all live sandbox sessions on graceful shutdown (FR-SANDBOX-4, #316).

    Iterates over active sandbox sessions and best-effort tears each down so
    ephemeral containers / VMs are not left running after the process exits.
    """
    sandbox = getattr(container, "sandbox", None)
    if sandbox is None:
        return
    try:
        active = getattr(sandbox, "active_sessions", lambda: [])()
        if not active:
            log.info("sandbox_cleanup_no_active_sessions")
            return
        for session in active:
            try:
                sandbox.teardown(session.session_id)
                log.info("sandbox_teardown_on_shutdown", session_id=session.session_id)
            except Exception as exc:  # pragma: no cover - defensive
                log.warning(
                    "sandbox_teardown_on_shutdown_failed",
                    session_id=session.session_id,
                    error=str(exc),
                )
        log.info("sandbox_cleanup_completed", count=len(active))
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("sandbox_cleanup_failed", error=str(exc))


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
    while not _shutdown_requested:
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
        if _shutdown_requested:
            break
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(app: FastAPI):
    container = app.state.container
    scheduler_task: asyncio.Task | None = None

    # 0) Register graceful-shutdown signal handlers (SIGTERM/SIGINT).
    _register_shutdown_signals()

    # 0b) Startup capability report — log which optional capabilities are REAL vs
    #    stub/degraded so operators can see the engine's effective configuration
    #    without digging through adapter code or waiting for a silent failure.
    try:
        caps = capability_status(
            browser_real=getattr(container.settings, "browser_real", False),
            postgres_engine=getattr(container, "engine", None),
        )
        for cap, status in caps.items():
            is_real = status.startswith("ok")
            log.info(
                "capability_status",
                capability=cap,
                status=status,
                real=is_real,
            )
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("capability_status_failed", error=str(exc))

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
        if healthy:
            log.info("db_healthcheck", healthy=healthy)
        else:
            # #312 — fail LOUD: the storage layer degraded to non-persistent
            # in-memory mode because the database was unreachable. This is NOT a
            # silent fallback; surface it so operators (and /healthz) see degraded.
            log.warning(
                "db_healthcheck",
                healthy=healthy,
                degraded="database unreachable — running on non-persistent in-memory storage; data will NOT survive restart",
            )
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

    # 3b) Start the audit-log service — subscribes to the domain event bus and
    #     persists one ActionEvent per emission (FR-LOG-4, FR-OBS-2). Process-lived;
    #     each handler opens its own DB session so the audit trail survives rollbacks.
    try:
        from applicant.application.services.audit_log_service import AuditLogService

        session_factory = getattr(container, "session_factory", None)
        audit_log = AuditLogService(
            storage=container.storage,
            session_factory=session_factory,
        )
        audit_log.start()
        log.info("audit_log_started", session_isolated=session_factory is not None)
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("audit_log_start_failed", error=str(exc))

    # 3c) Seed the reserved system campaign so instance-level secrets (the LLM key,
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

    # Shutdown: stop the scheduler loop, flush checkpoints, clean up sandboxes,
    # then dispose the engine if present.
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

    # Flush any in-memory checkpoint state to disk (FR-DUR-1, #316).
    _flush_checkpoints(container)

    # Tear down all live sandbox sessions (FR-SANDBOX-4, #316).
    _cleanup_sandboxes(container)

    if getattr(container, "engine", None) is not None:
        container.engine.dispose()
        log.info("engine_disposed")
