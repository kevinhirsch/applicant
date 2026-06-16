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
from applicant.app.deps import get_container, require_llm_configured
from applicant.application.services.material_service import MaterialService
from applicant.core.errors import ReviewRequired
from applicant.core.ids import GeneratedDocumentId

router = APIRouter(
    prefix="/api/documents", tags=["documents"], dependencies=[Depends(require_llm_configured)]
)


def _material_service(container: Container) -> MaterialService:
    # Composed from the frozen container's adapters: storage + llm + both tailoring
    # engines + the local embedding port (variant clustering, FR-RESUME-6) + the
    # Phase 0 ConversionService (per-campaign engine choice, FR-RESUME-3a).
    return MaterialService(
        container.storage,
        container.llm,
        container.latex_tailor,
        embedding=container.embedding,
        docx_tailoring=container.docx_tailor,
        conversion_service=container.conversion_service,
    )


class TurnIn(BaseModel):
    kind: str  # "add" | "subtract" | "free_text"
    instruction: str = ""


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
def list_for_application(application_id: str, container: Container = Depends(get_container)) -> dict:
    """List generated docs for an application + whether the review gate is open."""
    docs = container.storage.documents.list_for_application(application_id)  # type: ignore[arg-type]
    return {
        "application_id": application_id,
        "items": [
            {"id": d.id, "type": d.type.value, "approved": d.approved, "content": d.content}
            for d in docs
        ],
        "all_approved": all(d.approved for d in docs) if docs else True,
    }


@router.post("/redline", status_code=200)
def redline(body: RedlineIn, container: Container = Depends(get_container)) -> dict:
    """Render the add/subtract redline for the review surface (FR-RESUME-8)."""
    result = _material_service(container).render_redline(
        body.variant_id, body.base_source, body.new_source  # type: ignore[arg-type]
    )
    return {
        "variant_id": result.variant_id,
        "additions": list(result.additions),
        "subtractions": list(result.subtractions),
        "rendered_html": result.rendered_html,
    }


@router.post("/{document_id}/review", status_code=201)
def open_review(document_id: str, container: Container = Depends(get_container)) -> dict:
    """Open the interactive review session for a document (FR-RESUME-8)."""
    session = _material_service(container).open_revision(GeneratedDocumentId(document_id))
    return _session_payload(session)


@router.post("/{document_id}/turn", status_code=201)
def submit_turn(document_id: str, body: TurnIn, container: Container = Depends(get_container)) -> dict:
    """Apply an add/subtract/free-text revision turn (FR-RESUME-8)."""
    try:
        session = _material_service(container).apply_turn(
            GeneratedDocumentId(document_id), body.kind, body.instruction
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _session_payload(session)


@router.post("/{document_id}/approve", status_code=201)
def approve(document_id: str, container: Container = Depends(get_container)) -> dict:
    """Approve the material, passing the review gate (FR-RESUME-8)."""
    doc = _material_service(container).approve(GeneratedDocumentId(document_id))
    return {"id": doc.id, "type": doc.type.value, "approved": doc.approved}


@router.post("/{document_id}/decline", status_code=201)
def decline(document_id: str, container: Container = Depends(get_container)) -> dict:
    """Decline the material (stays unapproved, blocks submission)."""
    doc = _material_service(container).decline(GeneratedDocumentId(document_id))
    return {"id": doc.id, "type": doc.type.value, "approved": doc.approved}


@router.post("/applications/{application_id}/ensure-submittable")
def ensure_submittable(application_id: str, container: Container = Depends(get_container)) -> dict:
    """Enforce the review gate before submission (FR-RESUME-8). 409 if unapproved."""
    try:
        _material_service(container).ensure_application_submittable(application_id)  # type: ignore[arg-type]
    except ReviewRequired as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return {"application_id": application_id, "submittable": True}
