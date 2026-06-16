"""App lifespan: startup recovers durable workflows + seeds dormant surfaces;
shutdown disposes the engine. DB connectivity is verified but tolerated absent
(so tests/first-boot work) (FR-DUR-1, FR-UI-2, FR-OBS-1).
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from applicant.dormant import seed_dormant_surfaces
from applicant.observability.logging import get_logger

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    container = app.state.container

    # 1) Recover interrupted durable workflows (FR-DUR-1).
    try:
        recovered = container.orchestrator.recover_pending()
        log.info("durable_recovery", recovered=len(recovered))
    except NotImplementedError:
        log.info("durable_recovery_skipped", reason="orchestrator backend not ready")

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
        log.warning("dormant_seed_failed", error=str(exc))

    yield

    # Shutdown: dispose the engine if present.
    if getattr(container, "engine", None) is not None:
        container.engine.dispose()
        log.info("engine_disposed")
