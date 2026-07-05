"""FastAPI entrypoint. ``app = create_app()`` builds everything.

Composition: configure logging -> build container -> create app with lifespan ->
mount static -> register routers. This is the driving adapter at the edge of the
hexagon.
"""

from __future__ import annotations

import os
import traceback

from fastapi import FastAPI, Request
from fastapi.middleware.gzip import GZipMiddleware
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
from applicant.observability.capabilities import capability_status
from applicant.observability.logging import configure_logging, get_logger
from applicant.version import __version__

log = get_logger(__name__)

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

    Also installs a global catch-all for unhandled exceptions that logs the full
    context server-side (path, request-id, traceback) while returning a generic
    500 to the client — so crashes never leak internal detail/tracebacks to the
    browser (security) and are never opaque to operators (observability).

    Registered globally so any domain/rule violation that a specific route forgot
    to catch still returns the right status instead of a 500 with a leaked
    traceback. Per-route handling can stay; this is the safety net.
    """

    @app.exception_handler(DomainError)
    async def _domain_error_handler(_request: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(status_code=_status_for(exc), content={"detail": str(exc)})

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """Catch-all for any exception not handled by a more specific handler.

        Logs the path, optional request-id header, exception type and full
        traceback server-side so the cause is always diagnosable. Returns a
        generic 500 to the client — never a raw traceback or internal detail
        (security: no information leakage to untrusted callers).
        """
        request_id = request.headers.get("x-request-id") or request.headers.get("x-correlation-id")
        log.error(
            "unhandled_exception",
            path=request.url.path,
            method=request.method,
            request_id=request_id,
            exc_type=type(exc).__name__,
            detail=traceback.format_exc(),
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "An unexpected error occurred. Please try again later."},
        )


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build and return the fully-wired FastAPI application."""
    settings = settings or get_settings()
    configure_logging(log_format=settings.log_format, log_level=settings.log_level)

    container = build_container(settings)

    app = FastAPI(title="Applicant", version=__version__, lifespan=lifespan)
    app.state.container = container

    # Response compression (perf lens finding #1). This is currently the only
    # middleware on this app, so there is no ordering to get wrong yet — but
    # per Starlette semantics (the LAST `add_middleware` call becomes the
    # OUTERMOST wrapper, same as the ordering note in workspace/app.py), if any
    # more middleware is added later it should be registered BEFORE this call
    # so GZip stays outermost and compresses the final response every other
    # layer produces, not an intermediate one.
    app.add_middleware(GZipMiddleware, minimum_size=1000)

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
        DB check is treated as satisfied — that path has no Postgres to probe — but
        ``checks.database_persistence`` still honestly reports whether storage is a
        data-losing in-memory fallback (never flips the top-level status; see
        below). ``checks.capabilities``/``checks.capabilities_degraded`` likewise
        surface optional-capability gaps (missing browser/TeX/LibreOffice/etc.)
        without ever failing this probe hard for an optional gap.
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
            # (lens04 #1) `engine is None` alone does not say WHY: it is the same
            # signal for "no Postgres configured for this (dev/hermetic-test) boot"
            # and for "DATABASE_URL was unreachable and the container silently
            # degraded to InMemoryStorage(is_fallback=True)" (container.py, #312).
            # The coarse ok/degraded gate above stays green either way — the
            # hermetic/dev lane legitimately runs on in-memory storage — but a
            # data-losing fallback must never be indistinguishable from that
            # legitimate case in the payload. Consult the storage's own honesty
            # signal (`healthcheck()` returns `not is_fallback`) and report it as
            # its own field so a typo'd DATABASE_URL in prod is visible to an
            # operator even though this branch does not flip `ok`.
            storage_obj = getattr(app.state.container, "storage", None)
            is_fallback = True
            if storage_obj is not None and hasattr(storage_obj, "healthcheck"):
                try:
                    is_fallback = not storage_obj.healthcheck()
                except Exception:  # noqa: BLE001 - never let this probe crash healthz
                    is_fallback = True
            checks["database_persistence"] = (
                "degraded: in-memory fallback active — data will NOT persist "
                "across restarts"
                if is_fallback
                else "ok"
            )

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

        # 3) Optional-capability status (informational — does not affect ok/degraded).
        #    Reports which optional binaries/services are REAL vs stub so operators
        #    can confirm the deployed image has all expected capabilities without
        #    needing to grep logs or trigger a silent failure first.
        caps = capability_status(
            browser_real=getattr(container.settings, "browser_real", False),
            postgres_engine=engine,
        )
        checks["capabilities"] = caps
        # (lens04 #38) A missing optional binary (e.g. no browser for pre-fill,
        # no TeX/LibreOffice for résumé rendering) is deliberately informational
        # here — it never fails healthz hard, since it may be an intentionally
        # disabled feature rather than a broken deploy. But leaving it buried in
        # free-text per-capability strings means nothing actually surfaces the
        # degradation at a glance. Flatten it into a plain list of the
        # capabilities that are NOT "ok" so an operator (or an automated deploy
        # check) can see a degraded image without parsing prose.
        checks["capabilities_degraded"] = sorted(
            name for name, status in caps.items() if not status.startswith("ok")
        )

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
