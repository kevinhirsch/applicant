# routes/applicant_model_connections_routes.py
"""Applicant MODEL-ENDPOINT EDIT/REMOVE + CONVERSION-PREVIEW-DOWNLOAD proxy
(dark-engine audit items 19 and 20).

A small, standalone sibling of ``applicant_setup_routes.py`` — deliberately
kept in its own file (rather than appended there) to avoid touching that
in-flight file while another change is being developed against it. It mounts
UNDER THE SAME PREFIX (``/api/applicant/setup``) so the two new URL surfaces
sit exactly where a user of the setup wizard/model-ladder panel would expect
them, with zero path/method overlap with the sibling file's own routes:

  * ``PATCH``/``DELETE /api/applicant/setup/model-endpoints/{endpoint_id}`` —
    the engine has exposed ``PATCH``/``DELETE /api/model-endpoints/{id}``
    since the endpoint registry was built
    (``src/applicant/app/routers/model_endpoints.py``), but the sibling proxy
    only ever covered list/add/test/models — so a stale or mistyped endpoint
    accumulated forever with no way to edit or remove it (dark-engine audit
    item 20).
  * ``GET /api/applicant/setup/conversion/{campaign_id}/preview/download`` —
    the engine has served the compiled LaTeX conversion preview PDF at
    ``GET /api/conversion/{campaign_id}/preview/download`` since issue #178
    (``src/applicant/app/routers/conversion.py``), but the onboarding
    accept/reject step never let the user open it -- the decision was made
    from the page-count/fidelity summary alone (dark-engine audit item 19).

Same conventions as every other Applicant proxy lane: thin, 1:1 mapping onto
:class:`src.applicant_engine.ApplicantEngineClient`, typed :class:`EngineError`
translated into a clean JSON error (502 unreachable / engine status forwarded),
and the same ``can_configure`` config-privilege gate the sibling file uses for
its own model-endpoint add/test routes (editing/removing a saved endpoint is a
configuration action, not a plain read). The preview download is a plain read
(same tier as the sibling's own ``conversion_engine`` GET).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from src.applicant_engine import ApplicantEngineClient, EngineError
from src.auth_helpers import require_privilege, require_user

logger = logging.getLogger(__name__)

#: Matches ``applicant_setup_routes._CONFIG_PRIV`` — kept as a separate
#: constant (not imported) so this file has no import-time dependency on the
#: sibling module under active development.
_CONFIG_PRIV = "can_configure"


def _engine_error_response(exc: EngineError) -> JSONResponse:
    """Translate a typed :class:`EngineError` into a clean JSON error response.

    Mirrors ``applicant_setup_routes._engine_error_response`` exactly (kept as
    a local copy rather than a cross-module import for the same
    avoid-touching-the-sibling-file reason as the constant above).
    """
    if exc.status is None:
        message = (
            "The application engine timed out."
            if exc.is_timeout
            else "The application engine is unavailable."
        )
        return JSONResponse(
            status_code=502,
            content={"error": "engine_error", "message": message, "engine_status": None},
        )
    if exc.status >= 500:
        logger.warning(
            "engine 5xx (model-connections): status=%s detail=%s", exc.status, exc.detail or exc.message
        )
        return JSONResponse(
            status_code=502,
            content={
                "error": "engine_error",
                "message": "The application engine reported an error.",
                "engine_status": exc.status,
            },
        )
    return JSONResponse(
        status_code=exc.status,
        content={
            "error": "engine_error",
            "message": "The application engine reported an error.",
            "engine_status": exc.status,
            "detail": exc.detail,
        },
    )


def setup_applicant_model_connections_routes() -> APIRouter:
    """Build the model-endpoint edit/remove + conversion-preview-download
    proxy router (mounted in ``app.py`` alongside the other Applicant lanes)."""
    router = APIRouter(prefix="/api/applicant/setup", tags=["applicant-setup"])

    @router.patch("/model-endpoints/{endpoint_id}")
    async def patch_model_endpoint(endpoint_id: str, request: Request) -> JSONResponse:
        """Toggle a saved model endpoint enabled/disabled (dark-engine audit
        item 20; engine ``PATCH /api/model-endpoints/{id}``)."""
        require_privilege(request, _CONFIG_PRIV)
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.patch_model_endpoint(endpoint_id)
        except EngineError as exc:
            logger.info("applicant patch model endpoint failed: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data)

    @router.delete("/model-endpoints/{endpoint_id}")
    async def delete_model_endpoint(endpoint_id: str, request: Request) -> JSONResponse:
        """Remove a saved model endpoint (dark-engine audit item 20; engine
        ``DELETE /api/model-endpoints/{id}``) so stale or mistyped endpoints
        don't accumulate forever in the engine's own registry."""
        require_privilege(request, _CONFIG_PRIV)
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.delete_model_endpoint(endpoint_id)
        except EngineError as exc:
            logger.info("applicant delete model endpoint failed: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data)

    @router.get("/conversion/{campaign_id}/preview/download")
    async def conversion_preview_download(campaign_id: str, request: Request):
        """Download the compiled LaTeX conversion PREVIEW PDF (dark-engine
        audit item 19; engine ``GET /api/conversion/{campaign_id}/preview/
        download``). A plain read so the user can open the polished version
        being asked about before deciding accept/reject, rather than judging
        it from the summary line alone."""
        require_user(request)
        try:
            async with ApplicantEngineClient() as engine:
                resp = await engine.download_conversion_preview_pdf(campaign_id)
        except EngineError as exc:
            logger.info("applicant conversion preview download failed: %s", exc)
            return _engine_error_response(exc)
        return Response(
            content=resp.content,
            media_type=resp.headers.get("content-type", "application/pdf"),
            headers={
                "Content-Disposition": f"attachment; filename=resume-preview-{campaign_id}.pdf"
            },
        )

    return router
