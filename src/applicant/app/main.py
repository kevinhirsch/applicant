"""FastAPI entrypoint. ``app = create_app()`` builds everything.

Composition: configure logging -> build container -> create app with lifespan ->
mount static -> register routers. This is the driving adapter at the edge of the
hexagon.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from applicant.app.config import Settings, get_settings
from applicant.app.container import build_container
from applicant.app.lifespan import lifespan
from applicant.app.routers import register_routers
from applicant.app.static import mount_static
from applicant.core.errors import (
    ConfirmationRequired,
    DomainError,
    IllegalStateTransition,
    InvalidInput,
    LLMNotConfigured,
    NotFound,
    OnboardingIncomplete,
    ReviewRequired,
    SensitiveFieldViolation,
    TruthfulnessViolation,
)
from applicant.observability.logging import configure_logging
from applicant.version import __version__

#: Canonical HTTP status for each mapped domain error. The catch-all
#: :class:`DomainError` falls through to 400 so a rule violation never leaks a 500
#: with a traceback (the "mapped in route A, forgotten in route B" safety net).
_DOMAIN_ERROR_STATUS: dict[type[DomainError], int] = {
    ReviewRequired: 409,
    IllegalStateTransition: 409,
    ConfirmationRequired: 409,
    OnboardingIncomplete: 409,
    LLMNotConfigured: 409,
    SensitiveFieldViolation: 422,
    TruthfulnessViolation: 422,
    InvalidInput: 422,
    NotFound: 404,
}


def _status_for(exc: DomainError) -> int:
    # Exact-type lookup first, then walk the MRO so subclasses inherit a mapping.
    for cls in type(exc).__mro__:
        if cls in _DOMAIN_ERROR_STATUS:
            return _DOMAIN_ERROR_STATUS[cls]
    return 400


def register_exception_handlers(app: FastAPI) -> None:
    """Map domain errors to canonical 4xx with a clean ``{"detail": ...}`` body.

    Registered globally so any domain/rule violation that a specific route forgot
    to catch still returns the right status instead of a 500 with a leaked
    traceback. Per-route handling can stay; this is the safety net.
    """

    @app.exception_handler(DomainError)
    async def _domain_error_handler(_request: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(status_code=_status_for(exc), content={"detail": str(exc)})


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build and return the fully-wired FastAPI application."""
    settings = settings or get_settings()
    configure_logging(log_format=settings.log_format, log_level=settings.log_level)

    container = build_container(settings)

    app = FastAPI(title="Applicant", version=__version__, lifespan=lifespan)
    app.state.container = container

    mount_static(app, settings.app_static_dir)
    register_routers(app)
    register_exception_handlers(app)

    @app.get("/healthz", tags=["ops"])
    def healthz() -> dict:
        return {"status": "ok", "version": __version__}

    return app


app = create_app()
