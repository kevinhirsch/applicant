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
from typing import Any, Optional

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from src.applicant_engine import ApplicantEngineClient, EngineError, engine_base_url
from src.auth_helpers import require_engine_owner, require_privilege, require_user

logger = logging.getLogger(__name__)

#: Timeout for the standalone JD-match GET below — mirrors
#: ``applicant_engine._DEFAULT_TIMEOUT`` (a short, in-network read; deliberately
#: NOT imported from there since that constant is private to the module).
_JD_MATCH_TIMEOUT = httpx.Timeout(connect=3.0, read=15.0, write=5.0, pool=3.0)


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


class CoverLetterFillIn(BaseModel):
    """Merge-fill a user's OWN saved cover-letter template (dark-engine audit item
    41). Complementary to ``CoverLetterIn``'s on-demand LLM draft: the user pastes
    a template with ``{{field}}`` placeholders plus the values to substitute, and
    gets the filled text back -- pure string substitution, no LLM call, no
    fabrication risk."""

    template: str
    context: dict[str, str] = {}


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


class DeferredEssayIn(BaseModel):
    """Resolve a DEFERRED essay screening question pre-fill parked instead of
    auto-answering (dark-engine audit item 21). ``true_source`` defaults blank
    so the engine derives the ground truth server-side, matching
    ``CoverLetterIn``/``ScreeningAnswerIn``'s precedent above; ``selector`` is
    what lets the engine clear the originating ``agent_question`` pending
    action once the draft is generated."""

    campaign_id: str
    application_id: str
    true_source: str = ""
    label: str = ""
    question: str | None = None
    selector: str | None = None
    url: str | None = None
    explicit_answer: str | None = None


class RedlineIn(BaseModel):
    """Render a standalone add/subtract/highlighted-HTML redline between two
    arbitrary text sources (dark-engine audit item 22) -- a pure, stateless
    diff with no persistence, usable outside a review session (e.g. "compare
    to the original" once a document has been edited)."""

    variant_id: str
    base_source: str
    new_source: str
    aggressiveness: int = 20


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


async def _fetch_jd_match(application_id: str) -> Any:
    """Inline GET of the engine's résumé <-> JD keyword-match score (#23).

    ``applicant_engine.py`` is CONCURRENTLY LOCKED by another lane, so this is a
    deliberately small, self-contained httpx call mirroring
    ``ApplicantEngineClient._request``'s own timeout/error-normalization shape
    (timeout / connection failure -> :class:`EngineError` with ``status=None``;
    an HTTP error response -> :class:`EngineError` carrying the engine's status
    + detail) rather than a new method on the shared client. A small, acceptable
    duplication that keeps the two files independently editable.
    """
    url = f"{engine_base_url()}/api/documents/jd-match/{application_id}"
    try:
        async with httpx.AsyncClient(timeout=_JD_MATCH_TIMEOUT) as client:
            resp = await client.get(url)
    except httpx.TimeoutException as exc:
        raise EngineError(
            f"Engine request timed out: GET {url}", is_timeout=True
        ) from exc
    except httpx.HTTPError as exc:
        raise EngineError(f"Engine request failed: GET {url}: {exc}") from exc

    if resp.status_code >= 400:
        try:
            detail = resp.json()
        except ValueError:
            detail = resp.text
        raise EngineError(
            f"Engine returned HTTP {resp.status_code} for GET {url}",
            status=resp.status_code,
            detail=detail,
        )
    if resp.status_code == 204 or not resp.content:
        return None
    try:
        return resp.json()
    except ValueError:
        return resp.text


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

    @router.get("/{document_id}/flagged-facts")
    async def flagged_facts(document_id: str, request: Request) -> JSONResponse:
        """Facts in a generated draft not yet in the owner's profile (P1-13; engine
        ``GET /api/documents/{id}/flagged-facts``).

        The balanced truth policy lets the assistant rewrite freely and SURFACES
        invented fact-class tokens rather than blocking them; this read hands the
        review surface the tokens to double-check, each with a one-tap "yes, that's
        true, add to my profile" / "remove" choice. Flagged facts are profile gaps /
        draft personal facts — owner data on the single-tenant engine — so this read
        is gated with ``require_engine_owner`` (DISC-15), not plain ``require_user``.
        Degrades to an empty list on an engine error rather than blocking the review
        card."""
        require_engine_owner(request)
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.document_flagged_facts(document_id)
        except EngineError as exc:
            logger.info("applicant flagged-facts unavailable: %s", exc)
            return JSONResponse(
                content={"document_id": document_id, "flagged": []}
            )
        return JSONResponse(content=data)

    @router.get("/jd-match/{application_id}")
    async def jd_match(application_id: str, request: Request) -> JSONResponse:
        """Résumé <-> job-posting keyword match score for the redline surface
        (product-gaps backlog #23; engine ``GET /api/documents/jd-match/{id}``).

        Plain-language ``{score, matched, missing}``: which of the posting's
        keywords already show up in the candidate's résumé, and the
        highest-signal ones that don't. Pure/deterministic on the engine side —
        this proxy is a plain read, same auth tier as ``application_documents``
        above (the materials for an application are visible to any logged-in
        user of this single-tenant deployment)."""
        require_user(request)
        try:
            data = await _fetch_jd_match(application_id)
        except EngineError as exc:
            logger.info("applicant jd-match unavailable: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data)

    @router.get("/research-provenance/{application_id}")
    async def research_provenance(application_id: str, request: Request) -> JSONResponse:
        """Which company research (if any) informed this application's materials
        (dark-engine audit #76; engine ``GET /api/admin/research-provenance/{id}``).

        The capped deep-research escalation folds a company report into an
        application's materials when the agent hits a genuine knowledge gap, but
        which report -- if any -- lived only in the engine's checkpoint before now.
        Same auth tier as ``application_documents``/``jd_match`` above (the
        materials for an application are visible to any logged-in user of this
        single-tenant deployment); the redline review surface fetches this
        alongside the document/redline data to show a "research used" badge +
        excerpt. Degrades to ``{"used": false}`` on an engine error rather than
        blocking the review card."""
        require_user(request)
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.admin_research_provenance(application_id)
        except EngineError as exc:
            logger.info("applicant research-provenance unavailable: %s", exc)
            return JSONResponse(content={"application_id": application_id, "used": False})
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

    @router.get("/variants/{variant_id}/download")
    async def download_variant(variant_id: str, request: Request):
        """Download the compiled résumé PDF for a variant (dark-engine audit item
        16; engine ``GET /api/documents/variants/{variant_id}/download``).

        The engine route takes only a bare ``variant_id`` (no campaign to check
        directly), so this proxy fans out over the caller's OWN
        ``list_campaigns()`` -> ``list_variants()`` results and only forwards the
        download when the variant turns up under one of them -- mirrors
        ``_owner_campaign_ids``'s isolation boundary elsewhere in this file."""
        require_user(request)
        async with ApplicantEngineClient() as engine:
            owned = await _owner_campaign_ids(engine)
            if owned is None:
                raise HTTPException(status_code=503, detail="The engine is unavailable.")
            found = False
            for cid in owned:
                try:
                    data = await engine.list_variants(cid)
                except EngineError:
                    continue
                variants = data.get("variants") if isinstance(data, dict) else None
                if isinstance(variants, list) and any(
                    isinstance(v, dict) and str(v.get("variant_id")) == variant_id
                    for v in variants
                ):
                    found = True
                    break
            if not found:
                raise HTTPException(status_code=404, detail="No such résumé variant.")
            try:
                resp = await engine.download_variant_pdf(variant_id)
            except EngineError as exc:
                logger.info("applicant variant download failed: %s", exc)
                return _engine_error_response(exc)
        from fastapi.responses import Response

        return Response(
            content=resp.content,
            media_type=resp.headers.get("content-type", "application/pdf"),
            headers={
                "Content-Disposition": f"attachment; filename=resume-{variant_id}.pdf"
            },
        )

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

    @router.post("/cover-letter/fill")
    async def fill_cover_letter_template(body: CoverLetterFillIn, request: Request) -> JSONResponse:
        """Merge-fill a user's OWN saved cover-letter template (engine
        ``POST /api/documents/cover-letter/fill``; dark-engine audit item 41).

        Complementary to ``/cover-letter`` above: deterministic ``{{field}}``
        substitution, no LLM call. Same write privilege as the other on-demand
        generation routes -- it still produces application material, just without
        the LLM in the loop."""
        require_privilege(request, "can_use_documents")
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.fill_cover_letter_template(body.model_dump())
        except EngineError as exc:
            logger.info("applicant cover-letter template fill failed: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data)

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

    @router.post("/deferred-essay")
    async def generate_deferred_essay(body: DeferredEssayIn, request: Request) -> JSONResponse:
        """Resolve a DEFERRED essay screening question pre-fill parked instead of
        auto-answering (engine ``POST /api/documents/deferred-essay``; dark-engine
        audit item 21). Generates + routes the answer to review; the engine
        itself clears the originating ``agent_question`` Portal item when a
        ``selector`` is supplied, so the caller need not resolve it separately."""
        require_privilege(request, "can_use_documents")
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.generate_deferred_essay(body.model_dump())
        except EngineError as exc:
            logger.info("applicant deferred-essay generation failed: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data, status_code=201)

    @router.post("/redline")
    async def redline(body: RedlineIn, request: Request) -> JSONResponse:
        """Render a standalone add/subtract/highlighted-HTML redline between two
        arbitrary text sources (engine ``POST /api/documents/redline``; dark-engine
        audit item 22). A plain, stateless computation over caller-supplied
        strings (no storage write) -- same read-only auth tier as ``jd_match``
        above, reused by the review surface's "compare to original" control."""
        require_user(request)
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.render_redline(body.model_dump())
        except EngineError as exc:
            logger.info("applicant redline render failed: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data)

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

    @router.post("/variants/{variant_id}/promote")
    async def promote_variant(variant_id: str, request: Request) -> JSONResponse:
        """Promote a résumé variant to become the new base résumé future
        tailoring forks from, instead of the user's original base résumé
        (dark-engine audit item 33; engine
        ``POST /api/documents/variants/{id}/promote``).

        The engine route takes only a bare ``variant_id`` (no campaign to check
        directly), so this proxy fans out over the caller's OWN
        ``list_campaigns()`` -> ``list_variants()`` results and only forwards the
        promote when the variant turns up under one of them -- mirrors
        ``_owner_campaign_ids``'s isolation boundary elsewhere in this file (the
        engine has no owner concept of its own, so this check is the ONLY
        isolation boundary: a caller must not be able to promote a variant
        belonging to another owner's campaign)."""
        require_privilege(request, "can_use_documents")
        async with ApplicantEngineClient() as engine:
            owned = await _owner_campaign_ids(engine)
            if owned is None:
                raise HTTPException(status_code=503, detail="The engine is unavailable.")
            found = False
            for cid in owned:
                try:
                    data = await engine.list_variants(cid)
                except EngineError:
                    continue
                variants = data.get("variants") if isinstance(data, dict) else None
                if isinstance(variants, list) and any(
                    isinstance(v, dict) and str(v.get("variant_id")) == variant_id
                    for v in variants
                ):
                    found = True
                    break
            if not found:
                raise HTTPException(status_code=404, detail="No such résumé variant.")
            try:
                data = await engine.promote_variant(variant_id)
            except EngineError as exc:
                logger.info("applicant variant promote failed: %s", exc)
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
