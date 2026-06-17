"""Documents router (FR-RESUME-1/8, FR-ANSWER-1, FR-RESUME-9/10).

# STAGE B — owned by Phase 3.

Exposes the DocumentReview driving port: present the redline (add+subtract
highlights), run the interactive add/subtract/free-text revision loop, and
approve/decline. No submission until the material is approved (review gate,
FR-RESUME-8). The MaterialService is composed from the frozen container's
adapters (storage + llm + latex_tailor) so wiring stays in the composition root.
Gated behind the LLM-settings gate (FR-UI-5).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from applicant.app.container import Container
from applicant.app.deps import (
    get_material_service,
    get_pending_actions_service,
    get_storage,
    require_llm_configured,
    require_tool_enabled,
)
from applicant.application.services.material_service import MaterialService
from applicant.core.errors import NotFound, ReviewRequired
from applicant.core.ids import GeneratedDocumentId, ResumeVariantId

router = APIRouter(
    prefix="/api/documents", tags=["documents"], dependencies=[Depends(require_llm_configured)]
)


def _material_service(container: Container) -> MaterialService:
    # CONC-REQ-1: prefer the PER-REQUEST material service (its storage is bound to a
    # request-scoped Session). Composed from the frozen container's adapters.
    if container.material_service is not None:
        return container.material_service
    return MaterialService(
        container.storage,
        container.llm,
        container.latex_tailor,
        embedding=container.embedding,
        docx_tailoring=container.docx_tailor,
        conversion_service=container.conversion_service,
        notifications=container.notification_service,
        pending_actions=container.pending_actions_service,
        learning=container.learning_service,
        advanced_learning=container.advanced_learning_service,
    )


class TurnIn(BaseModel):
    kind: str  # "add" | "subtract" | "free_text"
    instruction: str = ""
    true_source: str | None = None  # enables the fabrication guardrail on the turn


class CoverLetterIn(BaseModel):
    campaign_id: str
    application_id: str
    true_source: str
    jd_terms: list[str] = []
    # On-demand decision (FR-RESUME-10): per-campaign default + optional role override.
    campaign_default: bool = False
    role_requires: bool | None = None


class ScreeningAnswerIn(BaseModel):
    campaign_id: str
    application_id: str
    question: str
    true_source: str
    # None -> classify (factual vs essay vs sensitive); else force essay/factual.
    essay: bool | None = None
    # Explicit stored EEO answer, used ONLY for sensitive fields (never AI-guessed).
    explicit_answer: str | None = None


class DeferredEssayIn(BaseModel):
    # #4: resolve a deferred essay screening question pre-fill recorded during the
    # FR-PREFILL-3 walk — generate + route the answer to review.
    campaign_id: str
    application_id: str
    true_source: str
    label: str = ""
    question: str | None = None
    selector: str | None = None
    url: str | None = None
    explicit_answer: str | None = None


class AggressivenessIn(BaseModel):
    # FR-RESUME-9 truthful-framing dial; the UI control ships grayed (FR-UI-2).
    aggressiveness: int = 20


class RedlineIn(BaseModel):
    variant_id: str
    base_source: str
    new_source: str
    # FR-RESUME-9 grayed aggressiveness control: accepted but not yet load-bearing.
    aggressiveness: int = 20


def _session_payload(session) -> dict:
    return {
        "session_id": session.id,
        "material_id": session.material_id,
        "status": session.status.value,
        "turns": [
            {"kind": t.kind, "instruction": t.instruction, "ai_response": t.ai_response}
            for t in session.turns
        ],
        "redline_state": session.redline_state,
    }


@router.get("")
def index() -> dict:
    return {"surface": "documents", "phase": 3, "status": "live"}


@router.get("/applications/{application_id}")
def list_for_application(
    application_id: str, storage=Depends(get_storage)
) -> dict:
    """List generated docs for an application + whether the review gate is open."""
    docs = storage.documents.list_for_application(application_id)  # type: ignore[arg-type]
    return {
        "application_id": application_id,
        "items": [
            {"id": d.id, "type": d.type.value, "approved": d.approved, "content": d.content}
            for d in docs
        ],
        "all_approved": all(d.approved for d in docs) if docs else True,
    }


@router.post(
    "/redline",
    status_code=200,
    dependencies=[Depends(require_tool_enabled("resume_tailoring"))],
)
def redline(body: RedlineIn, material=Depends(get_material_service)) -> dict:
    """Render the add/subtract redline for the review surface (FR-RESUME-8)."""
    result = material.render_redline(
        body.variant_id, body.base_source, body.new_source  # type: ignore[arg-type]
    )
    return {
        "variant_id": result.variant_id,
        "additions": list(result.additions),
        "subtractions": list(result.subtractions),
        "rendered_html": result.rendered_html,
    }


@router.post(
    "/cover-letter",
    status_code=201,
    dependencies=[Depends(require_tool_enabled("cover_letter_generation"))],
)
def generate_cover_letter(body: CoverLetterIn, material=Depends(get_material_service)) -> dict:
    """Generate a cover letter ON DEMAND (FR-RESUME-10), routed to review.

    Returns ``{"generated": false}`` when the role does not warrant one.
    """
    doc = material.generate_cover_letter(
        body.campaign_id,  # type: ignore[arg-type]
        body.application_id,  # type: ignore[arg-type]
        body.true_source,
        body.jd_terms,
        campaign_default=body.campaign_default,
        role_requires=body.role_requires,
    )
    if doc is None:
        return {"generated": False, "reason": "role does not warrant a cover letter"}
    return {"generated": True, "id": doc.id, "type": doc.type.value, "approved": doc.approved}


@router.post(
    "/screening-answer",
    status_code=201,
    dependencies=[Depends(require_tool_enabled("screening_answer_generation"))],
)
def generate_screening_answer(
    body: ScreeningAnswerIn, material=Depends(get_material_service)
) -> dict:
    """Generate a screening answer (FR-ANSWER-1): factual vs essay vs sensitive."""
    doc = material.generate_screening_answer(
        body.campaign_id,  # type: ignore[arg-type]
        body.application_id,  # type: ignore[arg-type]
        body.question,
        body.true_source,
        essay=body.essay,
        explicit_answer=body.explicit_answer,
    )
    return {"id": doc.id, "type": doc.type.value, "approved": doc.approved, "content": doc.content}


@router.post(
    "/deferred-essay",
    status_code=201,
    dependencies=[Depends(require_tool_enabled("screening_answer_generation"))],
)
def generate_deferred_essay(
    body: DeferredEssayIn,
    material=Depends(get_material_service),
    pending_actions=Depends(get_pending_actions_service),
) -> dict:
    """Generate + review the answer for a DEFERRED essay screening question (#4).

    Phase 2 pre-fill records essay screening questions it must not auto-answer as
    ``agent_question`` pending actions; this endpoint resolves one by generating the
    answer (classified, filtered, fabrication-gated) and routing it to review, and
    clears the originating pending action so the portal item does not linger.
    """
    deferred = {
        "label": body.label or body.question or "",
        "question": body.question,
        "selector": body.selector,
        "url": body.url,
        "explicit_answer": body.explicit_answer,
    }
    doc = material.generate_for_deferred_question(
        body.campaign_id,  # type: ignore[arg-type]
        body.application_id,  # type: ignore[arg-type]
        deferred,
        body.true_source,
    )
    # Resolve the originating agent_question pending action by its dedup key (#4/#7).
    if body.selector:
        try:
            pending_actions.resolve_by_dedup(
                body.campaign_id,  # type: ignore[arg-type]
                f"agent_question:{body.application_id}:{body.selector}",
            )
        except Exception:  # pragma: no cover - defensive
            pass
    return {"id": doc.id, "type": doc.type.value, "approved": doc.approved, "content": doc.content}


@router.post("/aggressiveness", status_code=200)
def set_aggressiveness(body: AggressivenessIn, material=Depends(get_material_service)) -> dict:
    """Set the truthful-framing dial (FR-RESUME-9). The UI control is grayed (FR-UI-2)."""
    value = material.set_aggressiveness(body.aggressiveness)
    return {"aggressiveness": value, "dormant_ui": True}


@router.post("/{document_id}/review", status_code=201)
def open_review(document_id: str, material=Depends(get_material_service)) -> dict:
    """Open the interactive review session for a document (FR-RESUME-8)."""
    session = material.open_revision(GeneratedDocumentId(document_id))
    return _session_payload(session)


@router.post("/{document_id}/turn", status_code=201)
def submit_turn(document_id: str, body: TurnIn, material=Depends(get_material_service)) -> dict:
    """Apply an add/subtract/free-text revision turn (FR-RESUME-8)."""
    try:
        session = material.apply_turn(
            GeneratedDocumentId(document_id),
            body.kind,
            body.instruction,
            true_source=body.true_source,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _session_payload(session)


@router.post("/{document_id}/approve", status_code=201)
def approve(document_id: str, material=Depends(get_material_service)) -> dict:
    """Approve the material, passing the review gate (FR-RESUME-8)."""
    doc = material.approve(GeneratedDocumentId(document_id))
    return {"id": doc.id, "type": doc.type.value, "approved": doc.approved}


@router.post("/variants/{variant_id}/approve", status_code=201)
def approve_variant(variant_id: str, material=Depends(get_material_service)) -> dict:
    """Approve a GENERATED resume variant through the review gate (#1, FR-RESUME-1/6/8).

    A generated variant routed to review (its material_review pending action + ping)
    is approved here, mirroring document approval. Approval clears the variant's
    pending action + ping and lets the parked pipeline advance past MATERIAL_REVIEW.
    """
    try:
        variant = material.approve_variant(ResumeVariantId(variant_id))
    except NotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return {
        "id": variant.id,
        "type": "resume_variant",
        "approved": variant.approved,
        "campaign_id": variant.campaign_id,
    }


@router.post("/{document_id}/decline", status_code=201)
def decline(document_id: str, material=Depends(get_material_service)) -> dict:
    """Decline the material (stays unapproved, blocks submission)."""
    doc = material.decline(GeneratedDocumentId(document_id))
    return {"id": doc.id, "type": doc.type.value, "approved": doc.approved}


@router.post("/applications/{application_id}/ensure-submittable")
def ensure_submittable(application_id: str, material=Depends(get_material_service)) -> dict:
    """Enforce the review gate before submission (FR-RESUME-8). 409 if unapproved."""
    try:
        material.ensure_application_submittable(application_id)  # type: ignore[arg-type]
    except ReviewRequired as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return {"application_id": application_id, "submittable": True}
