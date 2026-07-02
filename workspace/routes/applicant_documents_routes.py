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
  other data route. Reads + opening a review session require a logged-in user;
  the mutating operations (turn / approve / decline / variant-approve /
  aggressiveness) additionally require the ``can_use_documents`` privilege,
  matching the workspace's native documents surface (``routes/document_routes.py``)
  so a restricted user can't drive document writes through the proxy.
"""

from __future__ import annotations

import logging
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from src.applicant_engine import ApplicantEngineClient, EngineError
from src.auth_helpers import require_privilege, require_user

logger = logging.getLogger(__name__)


async def _owner_campaign_ids(engine: ApplicantEngineClient) -> Optional[set]:
    """The owner's campaign ids, or ``None`` when the engine is unreachable.

    Mirrors ``applicant_campaigns_routes._owner_campaign_ids``: the engine has no
    owner concept of its own (single-tenant per deployment, CLAUDE.md), so this
    request's own ``list_campaigns()`` fan-out is the ONLY scoping boundary for the
    screening-answer library -- never trust a caller-supplied ``campaign_id``.
    """
    try:
        campaigns = await engine.list_campaigns()
    except EngineError as exc:
        logger.debug("documents: campaigns read failed: %s", exc)
        return None
    if not isinstance(campaigns, list):
        return set()
    return {str(c.get("id")) for c in campaigns if isinstance(c, dict) and c.get("id")}

#: A redline revision turn is HEAVY writing — the engine runs the escalation (L2/pro)
#: tier, whose per-call budget is ~60s and which may escalate, so the default 30s read
#: timeout 502'd legitimate revisions before they returned. Give the turn a generous
#: read window so the model's revision lands instead of the proxy giving up.
_TURN_TIMEOUT = httpx.Timeout(connect=3.0, read=120.0, write=10.0, pool=3.0)


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


class BannedPhrasesIn(BaseModel):
    """The owner's "no-AI-look" phrase list (FR-RESUME-5). Each phrase is stripped
    from every generated resume/letter before it reaches review."""

    phrases: list[str] = []


class CoverLetterIn(BaseModel):
    """On-demand cover-letter generation request (FR-RESUME-10). The user clicks
    "generate" for an application; the ground-truth text is derived server-side, so
    the UI sends just the campaign + application (``role_requires`` forces it)."""

    campaign_id: str
    application_id: str
    jd_terms: list[str] = []
    campaign_default: bool = True
    role_requires: bool | None = True


class ScreeningAnswerIn(BaseModel):
    """On-demand screening-answer generation request (FR-ANSWER-1). The user supplies
    the question; the answer is drafted from the profile, voice-filtered, and
    review-gated before any use."""

    campaign_id: str
    application_id: str
    question: str
    essay: bool | None = None


class ScreeningAnswerReuseIn(BaseModel):
    """Reuse a saved library answer for a NEW application (product-gaps #20)
    instead of regenerating it fresh."""

    campaign_id: str
    application_id: str
    question: str


def _engine_error_response(exc: EngineError) -> JSONResponse:
    """Translate a typed :class:`EngineError` into a clean JSON error response.

    * timeout / connection failure (``status is None``) -> 502 Bad Gateway:
      the engine is down/unreachable, not a client mistake.
    * 4xx responses from the engine are forwarded (client-correctable: 404
      unknown document, 409 review-required) so the UI can react precisely.
    * 5xx responses are scrubbed: the raw detail may contain internal stack
      traces or state; we log it server-side and return a generic message.
    """
    if exc.status is None:
        status_code = 502
        message = (
            "The application engine timed out."
            if exc.is_timeout
            else "The application engine is unavailable."
        )
        return JSONResponse(
            status_code=status_code,
            content={"error": "engine_error", "message": message, "engine_status": None},
        )
    if exc.status >= 500:
        logger.warning("engine 5xx (documents): status=%s detail=%s", exc.status, exc.detail or exc.message)
        return JSONResponse(
            status_code=502,
            content={"error": "engine_error", "message": "The application engine reported an error.", "engine_status": exc.status},
        )
    # 4xx: pass detail through (client-correctable: 404 not found, 409 review-required).
    return JSONResponse(
        status_code=exc.status,
        content={
            "error": "engine_error",
            "message": "The application engine reported an error.",
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

    @router.get("/variants/{campaign_id}")
    async def variant_library(campaign_id: str, request: Request) -> JSONResponse:
        """The résumé-variant library for a job search — each variant's lineage,
        fit scores and approval state (engine ``GET /api/documents/variants/{id}``).
        Owner-scoped read; the user-facing equivalent of the admin Variants view."""
        require_user(request)
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.list_variants(campaign_id)
        except EngineError as exc:
            logger.info("applicant variant library unavailable: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data)

    # ── on-demand generation (FR-RESUME-10, FR-ANSWER-1) ─────────────────

    @router.post("/cover-letter")
    async def generate_cover_letter(body: CoverLetterIn, request: Request) -> JSONResponse:
        """Generate a cover letter for an application on demand (engine
        ``POST /api/documents/cover-letter``); the result lands in the review list.
        The ground-truth text is derived server-side from the profile."""
        require_privilege(request, "can_use_documents")
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.generate_cover_letter(body.model_dump())
        except EngineError as exc:
            logger.info("applicant cover-letter generation failed: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data, status_code=201)

    @router.post("/screening-answer")
    async def generate_screening_answer(body: ScreeningAnswerIn, request: Request) -> JSONResponse:
        """Draft an answer to a screening question on demand (engine
        ``POST /api/documents/screening-answer``); the result lands in the review
        list. Truthful, voice-filtered, and review-gated before any use."""
        require_privilege(request, "can_use_documents")
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.generate_screening_answer(body.model_dump())
        except EngineError as exc:
            logger.info("applicant screening-answer generation failed: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data, status_code=201)

    # ── screening-answer library (product-gaps backlog #20) ─────────────

    @router.get("/screening-answer-library/{campaign_id}")
    async def screening_answer_library(campaign_id: str, request: Request) -> dict:
        """The owner's saved screening-answer library for ONE OF THEIR OWN
        campaigns (engine ``GET /api/documents/screening-answer-library/{id}``).

        ``campaign_id`` is validated against this request's own ``list_campaigns()``
        fan-out BEFORE the read is forwarded -- mirrors
        ``applicant_campaigns_routes``'s owner-scoping (the engine itself has no
        owner concept, so this check is the only isolation boundary)."""
        require_user(request)
        async with ApplicantEngineClient() as engine:
            owned = await _owner_campaign_ids(engine)
            if owned is None:
                return {"engine_available": False, "campaign_id": campaign_id, "items": []}
            if campaign_id not in owned:
                return {"engine_available": True, "campaign_id": campaign_id, "items": []}
            try:
                data = await engine.screening_answer_library(campaign_id)
            except EngineError as exc:
                logger.debug("documents: screening-answer library read failed: %s", exc)
                return {"engine_available": True, "campaign_id": campaign_id, "items": []}
        out = data if isinstance(data, dict) else {}
        items = out.get("items") if isinstance(out.get("items"), list) else []
        return {"engine_available": True, "campaign_id": campaign_id, "items": items}

    @router.post("/screening-answer-library/reuse")
    async def reuse_screening_answer(
        body: ScreeningAnswerReuseIn, request: Request
    ) -> JSONResponse:
        """Reuse a saved library answer for a NEW application instead of
        regenerating it (engine ``POST /api/documents/screening-answer-library/
        reuse``). ``campaign_id`` is validated against this request's own owned
        campaigns BEFORE the write is forwarded -- a caller cannot reuse a library
        answer, or create a document, under a campaign that is not their own."""
        require_privilege(request, "can_use_documents")
        async with ApplicantEngineClient() as engine:
            owned = await _owner_campaign_ids(engine)
            if owned is None:
                raise HTTPException(status_code=503, detail="The engine is unavailable.")
            if body.campaign_id not in owned:
                raise HTTPException(status_code=404, detail="No such campaign.")
            try:
                data = await engine.reuse_screening_answer(body.model_dump())
            except EngineError as exc:
                logger.info("applicant screening-answer reuse failed: %s", exc)
                return _engine_error_response(exc)
        return JSONResponse(content=data, status_code=201)

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
        require_privilege(request, "can_use_documents")
        try:
            async with ApplicantEngineClient(timeout=_TURN_TIMEOUT) as engine:
                data = await engine.turn_document(document_id, body.model_dump())
        except EngineError as exc:
            logger.info("applicant document turn failed: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data)

    @router.post("/{document_id}/approve")
    async def approve(document_id: str, request: Request) -> JSONResponse:
        """Approve a document, passing the review gate
        (engine ``POST /api/documents/{id}/approve``)."""
        require_privilege(request, "can_use_documents")
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
        require_privilege(request, "can_use_documents")
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
        require_privilege(request, "can_use_documents")
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
        require_privilege(request, "can_use_documents")
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.set_document_aggressiveness(body.aggressiveness)
        except EngineError as exc:
            logger.info("applicant aggressiveness set failed: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data)

    # ── banned-phrase ("no-AI-look") list (FR-RESUME-5) ─────────────────

    @router.get("/banned-phrases")
    async def get_banned_phrases(request: Request) -> JSONResponse:
        """The owner's editable "no-AI-look" phrase list plus the curated baseline
        (engine ``GET /api/documents/banned-phrases``)."""
        require_user(request)
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.get_banned_phrases()
        except EngineError as exc:
            logger.info("applicant banned-phrases read unavailable: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data)

    @router.post("/banned-phrases")
    async def set_banned_phrases(body: BannedPhrasesIn, request: Request) -> JSONResponse:
        """Replace the owner's "no-AI-look" phrase list
        (engine ``POST /api/documents/banned-phrases``)."""
        require_privilege(request, "can_use_documents")
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.set_banned_phrases(body.phrases)
        except EngineError as exc:
            logger.info("applicant banned-phrases set failed: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data)

    # ── review gate: ensure-submittable (FR-RESUME-8) ───────────────────

    @router.post("/applications/{application_id}/ensure-submittable")
    async def ensure_submittable(application_id: str, request: Request) -> JSONResponse:
        """Enforce the review gate before submission (engine
        POST /api/documents/applications/{id}/ensure-submittable). Returns 409
        when the application has unapproved materials."""
        require_user(request)
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.ensure_submittable(application_id)
        except EngineError as exc:
            logger.info("applicant ensure-submittable failed: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data)

    return router
