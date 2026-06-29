"""Conversion router — LaTeX conversion preview + accept/reject gate (FR-RESUME-3a).

After the base resume is uploaded and fonts resolved, the system compiles the
LaTeX conversion and presents it for accept (LaTeX becomes the campaign's primary
engine) or reject (fall back to docx). The choice persists per campaign and is read
by Phase 3 material generation. Gated behind the LLM gate.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel

from applicant.app.deps import (
    get_conversion_service,
    get_onboarding_service,
    require_llm_configured,
)
from applicant.ports.driving.onboarding import IntakeSection

router = APIRouter(
    prefix="/api/conversion",
    tags=["conversion"],
    dependencies=[Depends(require_llm_configured)],  # FR-UI-5 gate
)


class PreviewIn(BaseModel):
    source: str = ""


def _base_source(campaign_id: str, onboarding) -> str:
    """Resolve LaTeX-conversion source from the uploaded base resume, if any."""
    state = onboarding.get_state(campaign_id)
    base = state.intake.get(IntakeSection.BASE_RESUME.value, {})
    path = base.get("document_path")
    if path and Path(path).is_file():
        try:
            return Path(path).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return ""
    return ""


@router.get("/{campaign_id}/engine")
def get_engine(campaign_id: str, svc=Depends(get_conversion_service)) -> dict:
    return {"campaign_id": campaign_id, "engine": svc.get_engine(campaign_id)}


@router.post("/{campaign_id}/preview")
def build_preview(
    campaign_id: str,
    body: PreviewIn,
    svc=Depends(get_conversion_service),
    onboarding=Depends(get_onboarding_service),
) -> dict:
    """Compile the LaTeX conversion of the base resume for accept/reject."""
    source = body.source or _base_source(campaign_id, onboarding)
    preview = svc.build_preview(campaign_id, source)
    return {
        "campaign_id": preview.campaign_id,
        "storage_path": preview.storage_path,
        "page_count": preview.page_count,
        "fidelity_ok": preview.fidelity_ok,
        "notes": preview.notes,
    }


@router.get("/{campaign_id}/preview/download")
def download_preview(
    campaign_id: str,
    svc=Depends(get_conversion_service),
    onboarding=Depends(get_onboarding_service),
) -> FileResponse:
    """Download the compiled LaTeX conversion PDF preview (issue #178).

    Returns the PDF when the real TeX engine produced output; 404 in stub mode.
    """
    source = _base_source(campaign_id, onboarding)
    preview = svc.build_preview(campaign_id, source)
    if preview.storage_path:
        p = Path(preview.storage_path)
        if p.is_file():
            return FileResponse(str(p), media_type="application/pdf", filename=p.name)
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Conversion preview PDF not available. Install a TeX engine and set RESUME_RENDER=auto.",
    )


@router.post("/{campaign_id}/accept")
def accept(campaign_id: str, svc=Depends(get_conversion_service)) -> dict:
    """ACCEPT -> LaTeX becomes the campaign's primary engine (FR-RESUME-3a)."""
    return {"campaign_id": campaign_id, "engine": svc.accept(campaign_id)}


@router.post("/{campaign_id}/reject")
def reject(campaign_id: str, svc=Depends(get_conversion_service)) -> dict:
    """REJECT -> fall back to the docx engine (FR-RESUME-3a)."""
    return {"campaign_id": campaign_id, "engine": svc.reject(campaign_id)}
