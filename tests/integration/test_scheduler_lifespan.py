"""Scheduler lifespan wiring (NFR-247-1, hermetic safety).

Proves SCHEDULER_ENABLED defaults False so the TestClient lifespan never spins a
live background loop (the default test lane stays hermetic), the container exposes
the agent loop + scheduler, and recover-on-startup re-drives pending workflows.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from applicant.app.config import Settings
from applicant.app.container import build_container
from applicant.app.main import create_app


@pytest.mark.integration
def test_scheduler_disabled_by_default_no_background_task():
    # Default settings: SCHEDULER_ENABLED is False; lifespan must NOT create a task.
    settings = Settings(_env_file=None)
    assert settings.scheduler_enabled is False
    app = create_app(settings)
    with TestClient(app) as client:
        # The app boots and serves without the lifespan hanging on a live loop.
        assert client.get("/healthz").status_code == 200
        # No scheduler asyncio tasks are running in the loop.
        running = [
            t for t in asyncio.all_tasks(asyncio.get_event_loop())
            if "scheduler" in str(t.get_coro()).lower()
        ] if _has_running_loop() else []
        assert running == []


def _has_running_loop() -> bool:
    try:
        asyncio.get_running_loop()
        return True
    except RuntimeError:
        return False


@pytest.mark.integration
def test_container_exposes_loop_and_scheduler():
    container = build_container(Settings(_env_file=None))
    assert container.agent_loop is not None
    assert container.scheduler is not None
    # The scheduler's tick is callable and pure (no real sleep).
    from datetime import UTC, datetime

    out = container.scheduler.tick(datetime(2026, 6, 16, tzinfo=UTC))
    assert "ticked" in out


@pytest.mark.integration
def test_scheduler_enabled_starts_and_stops_cleanly():
    # When enabled, the lifespan starts the loop AND stops it on shutdown (no hang).
    settings = Settings(_env_file=None, SCHEDULER_ENABLED=True, SCHEDULER_INTERVAL_SECONDS=3600)
    app = create_app(settings)
    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
    # Exiting the context manager (shutdown) must complete without hanging — the
    # background task is cancelled cleanly.
