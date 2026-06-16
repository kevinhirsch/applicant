"""FastAPI entrypoint. ``app = create_app()`` builds everything.

Composition: configure logging -> build container -> create app with lifespan ->
mount static -> register routers. This is the driving adapter at the edge of the
hexagon.
"""

from __future__ import annotations

from fastapi import FastAPI

from applicant.app.config import Settings, get_settings
from applicant.app.container import build_container
from applicant.app.lifespan import lifespan
from applicant.app.routers import register_routers
from applicant.app.static import mount_static
from applicant.observability.logging import configure_logging
from applicant.version import __version__


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build and return the fully-wired FastAPI application."""
    settings = settings or get_settings()
    configure_logging(log_format=settings.log_format, log_level=settings.log_level)

    container = build_container(settings)

    app = FastAPI(title="Applicant", version=__version__, lifespan=lifespan)
    app.state.container = container

    mount_static(app, settings.app_static_dir)
    register_routers(app)

    @app.get("/healthz", tags=["ops"])
    def healthz() -> dict:
        return {"status": "ok", "version": __version__}

    return app


app = create_app()
