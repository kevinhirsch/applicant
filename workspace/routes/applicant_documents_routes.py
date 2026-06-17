# routes/applicant_documents_routes.py
"""Applicant DOCUMENTS proxy — the workspace-side endpoints the Documents UI
calls to surface the engine's generated resume / cover-letter library and run the
redline change-and-review loop.

This is Lane A of the Stage-2 wiring (see ``workspace/APPLICANT_INTEGRATION.md``).
It is a thin, auth-protected proxy in front of the engine's ``documents`` router:
every handler delegates to :class:`src.applicant_engine.ApplicantEngineClient`
(the shared client) so URLs + error handling live in exactly one place.

Design notes:

* **No business logic here.** Each route maps 1:1 to an engine documents
  endpoint and hands back the engine's JSON unchanged, so the front-end renders
  the same shapes the engine produces.
* **Graceful degradation.** The engine client raises the typed
  :class:`EngineError` for timeouts / connection failures / HTTP 4xx-5xx; we
  translate those to a clean JSON error with a sensible status (502 when the
  engine is unreachable, or the engine's own status when it answered) instead of
  leaking a 500 + traceback. A wired Documents surface stays usable.
* **Activation is handled elsewhere.** The feature-activation layer
  (``/api/applicant/features``) greys this section in the nav until the engine's
  ``redline_surface`` is live + onboarding is complete, so these routes only get
  hit once the backing is configured. They still degrade safely if called early.
* **Auth.** Mounted on the normal (cookie/token-authenticated) surface — unlike
  the read-only ``/api/applicant/features`` probe, these act on the owner's real
  application materials, so they require an authenticated session like every
  other data route.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from src.applicant_engine import ApplicantEngineClient, EngineError
from src.auth_helpers import require_user

logger = logging.getLogger(__name__)


class TurnIn(BaseModel):
    """One revision turn in the review loop.

    ``kind`` is ``add`` | ``subtract`` | ``free_text`` (engine vocabulary);
    ``instruction`` is the user's plain-language change request; ``true_source``
    is the optional ground-truth text that arms the engine's fabrication
    guardrail for this turn.
    """

    kind: str = "free_text"
    instruction: str = ""
    true_source: str | None = None


class AggressivenessIn(BaseModel):
    """Truthful-framing dial (how assertively the wording leans). Plain integer
    0-100; the engine clamps + interprets it."""

    aggressiveness: int = 20


def _engine_error_response(exc: EngineError) -> JSONResponse:
    """Translate a typed :class:`EngineError` into a clean JSON error response.

    * timeout / connection failure (``status is None``) -> 502 Bad Gateway:
      the engine is down/unreachable, not a client mistake.
    * the engine answered with an HTTP error -> pass that status through (e.g.
      404 unknown document, 409 review-required) so the UI can react precisely.
    """
    if exc.status is None:
        status_code = 502
        message = (
            "The application engine timed out."
            if exc.is_timeout
            else "The application engine is unavailable."
        )
    else:
        status_code = exc.status
        message = "The application engine reported an error."
    return JSONResponse(
        status_code=status_code,
        content={
            "error": "engine_error",
            "message": message,
            "engine_status": exc.status,
            "detail": exc.detail,
        },
    )


def setup_applicant_documents_routes() -> APIRouter:
    """Build the Applicant documents proxy router (mounted in ``app.py``)."""
    router = APIRouter(prefix="/api/applicant/documents", tags=["applicant-documents"])

    # ── library / listing ──────────────────────────────────────────────

    @router.get("/library")
    async def library(request: Request) -> JSONResponse:
        """The generated resume / cover-letter library for the owner's
        applications (engine ``GET /api/documents``)."""
        require_user(request)
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.list_documents()
        except EngineError as exc:
            logger.info("applicant documents library unavailable: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data)

    @router.get("/applications/{application_id}")
    async def application_documents(application_id: str, request: Request) -> JSONResponse:
        """Documents for one application + whether the review gate is open
        (engine ``GET /api/documents/applications/{id}``)."""
        require_user(request)
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.documents_for_application(application_id)
        except EngineError as exc:
            logger.info("applicant documents for application unavailable: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data)

    # ── review / change loop ────────────────────────────────────────────

    @router.post("/{document_id}/review")
    async def open_review(document_id: str, request: Request) -> JSONResponse:
        """Open the interactive review session for a document — returns the
        redline + turn history (engine ``POST /api/documents/{id}/review``)."""
        require_user(request)
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.review_document(document_id)
        except EngineError as exc:
            logger.info("applicant document review unavailable: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data)

    @router.post("/{document_id}/turn")
    async def submit_turn(document_id: str, body: TurnIn, request: Request) -> JSONResponse:
        """Apply one change turn to a document under review
        (engine ``POST /api/documents/{id}/turn``)."""
        require_user(request)
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.turn_document(document_id, body.model_dump())
        except EngineError as exc:
            logger.info("applicant document turn failed: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data)

    @router.post("/{document_id}/approve")
    async def approve(document_id: str, request: Request) -> JSONResponse:
        """Approve a document, passing the review gate
        (engine ``POST /api/documents/{id}/approve``)."""
        require_user(request)
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.approve_document(document_id)
        except EngineError as exc:
            logger.info("applicant document approve failed: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data)

    @router.post("/{document_id}/decline")
    async def decline(document_id: str, request: Request) -> JSONResponse:
        """Decline a document — it stays unapproved and blocks submission
        (engine ``POST /api/documents/{id}/decline``)."""
        require_user(request)
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.decline_document(document_id)
        except EngineError as exc:
            logger.info("applicant document decline failed: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data)

    @router.post("/variants/{variant_id}/approve")
    async def approve_variant(variant_id: str, request: Request) -> JSONResponse:
        """Approve a generated resume variant through the review gate
        (engine ``POST /api/documents/variants/{id}/approve``)."""
        require_user(request)
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.approve_variant(variant_id)
        except EngineError as exc:
            logger.info("applicant variant approve failed: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data)

    # ── settings ────────────────────────────────────────────────────────

    @router.post("/aggressiveness")
    async def set_aggressiveness(body: AggressivenessIn, request: Request) -> JSONResponse:
        """Set the truthful-framing dial for generated wording
        (engine ``POST /api/documents/aggressiveness``)."""
        require_user(request)
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.set_document_aggressiveness(body.aggressiveness)
        except EngineError as exc:
            logger.info("applicant aggressiveness set failed: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data)

    return router
