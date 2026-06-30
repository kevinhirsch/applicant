"""FastAPI entrypoint. ``app = create_app()`` builds everything.

Composition: configure logging -> build container -> create app with lifespan ->
mount static -> register routers. This is the driving adapter at the edge of the
hexagon.
"""

from __future__ import annotations

import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from applicant.app.config import Settings, get_settings
from applicant.app.container import build_container
from applicant.app.lifespan import lifespan
from applicant.app.routers import register_routers
from applicant.app.routers.mcp import mount_mcp
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
    mount_mcp(app)

    @app.get("/healthz", tags=["ops"])
    def healthz() -> JSONResponse:
        """Readiness probe used by the prod healthcheck + install/update heartbeat.

        Returns 200 ``{"status":"ok"}`` only when the engine can actually serve:
        a trivial ``SELECT 1`` succeeds against the configured database AND the
        credential-vault key directory is writable. Any failure returns 503
        ``{"status":"degraded", ...}`` so the UI's ``depends_on: service_healthy``
        and the deploy heartbeat hold until the engine is genuinely ready, instead
        of going green while the DB is unreachable.

        Kept fast and dependency-light: one cheap query + one filesystem check. When
        no real DB is wired (the in-memory boot/test path, ``engine is None``) the
        DB check is treated as satisfied — that path has no Postgres to probe.
        """
        checks: dict[str, str] = {}
        ok = True

        # 1) Database reachability (the thing that actually matters at deploy time).
        engine = getattr(app.state.container, "engine", None)
        if engine is not None:
            try:
                with engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
                checks["database"] = "ok"
            except Exception as exc:  # noqa: BLE001 - report, never leak a traceback
                ok = False
                checks["database"] = f"error: {type(exc).__name__}"
        else:
            checks["database"] = "in-memory"

        # 2) Credential-vault key directory must be writable (else sealed secrets
        #    can't be read/written — a silent data-loss class). Cheap dir check.
        keydir = os.path.dirname(settings.credential_keyfile) or "."
        if os.path.isdir(keydir) and os.access(keydir, os.W_OK):
            checks["credential_keydir"] = "ok"
        elif not os.path.exists(keydir) and os.access(
            os.path.dirname(keydir) or ".", os.W_OK
        ):
            # Not yet created but its parent is writable (first boot creates it 0700).
            checks["credential_keydir"] = "pending"
        else:
            ok = False
            checks["credential_keydir"] = "not-writable"

        if ok:
            return JSONResponse(
                status_code=200,
                content={"status": "ok", "version": __version__, "checks": checks},
            )
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "version": __version__, "checks": checks},
        )

    return app


app = create_app()
