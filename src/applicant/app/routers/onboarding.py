"""Onboarding router — Workday-ready resumable intake (FR-ONBOARD-1/2/3).

Zero-CLI endpoints (NFR-ZEROCLI-1) for the comprehensive intake: get/resume the
state, save a step, complete (gated on required sections), and ingest the base
resume to bootstrap + reconcile the attribute cloud. Gated behind the LLM-settings
gate (FR-UI-5) like the rest of the application surface.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel

from applicant.app.deps import (
    get_container,
    get_onboarding_service,
    require_llm_configured,
)
from applicant.ports.driving.onboarding import IntakeSection

router = APIRouter(
    prefix="/api/onboarding",
    tags=["onboarding"],
    dependencies=[Depends(require_llm_configured)],  # FR-UI-5 gate
)


class SaveSectionIn(BaseModel):
    section: str
    data: dict


class ConfirmConflictIn(BaseModel):
    attribute: str
    value: str


def _state_dict(state) -> dict:
    return {
        "campaign_id": state.campaign_id,
        "complete": state.complete,
        "sections_complete": state.sections_complete,
        "missing_sections": state.missing_sections,
        "intake": state.intake,
    }


@router.get("/{campaign_id}")
def get_state(campaign_id: str, svc=Depends(get_onboarding_service)) -> dict:
    """Get / resume the intake state (FR-ONBOARD-2)."""
    return _state_dict(svc.get_state(campaign_id))


@router.post("/{campaign_id}/section")
def save_section(campaign_id: str, body: SaveSectionIn, svc=Depends(get_onboarding_service)) -> dict:
    """Persist one intake section's partial state (FR-ONBOARD-2)."""
    try:
        section = IntakeSection(body.section)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"unknown section: {body.section}"
        ) from exc
    return _state_dict(svc.save_section(campaign_id, section, body.data))


@router.post("/{campaign_id}/complete")
def complete(campaign_id: str, svc=Depends(get_onboarding_service)) -> dict:
    """Set the completion flag iff every required section is present (FR-ONBOARD-2)."""
    state = svc.complete(campaign_id)
    if not state.complete:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "Onboarding intake incomplete (FR-ONBOARD-2).",
                "missing_sections": state.missing_sections,
            },
        )
    return _state_dict(state)


@router.post("/{campaign_id}/base-resume")
async def ingest_base_resume(
    campaign_id: str,
    file: UploadFile = File(...),
    svc=Depends(get_onboarding_service),
    container=Depends(get_container),
) -> dict:
    """Parse the base resume + reconcile with interview answers (FR-ONBOARD-3)."""
    uploads = Path(tempfile.gettempdir()) / "applicant_uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    suffix = Path(file.filename or "resume.txt").suffix or ".txt"
    dest = uploads / f"{campaign_id}{suffix}"
    dest.write_bytes(await file.read())

    result = svc.ingest_base_resume(campaign_id, str(dest))
    return {
        "auto_applied": result.auto_applied,
        "attribute_count": result.attribute_count,
        "conflicts": [
            {
                "attribute": c.attribute,
                "interview_value": c.interview_value,
                "parsed_value": c.parsed_value,
            }
            for c in result.conflicts
        ],
        "requires_confirmation": bool(result.conflicts),
    }


@router.post("/{campaign_id}/confirm-conflict")
def confirm_conflict(
    campaign_id: str, body: ConfirmConflictIn, svc=Depends(get_onboarding_service)
) -> dict:
    """Apply a flagged integral change after explicit confirmation (FR-FB-3)."""
    svc.confirm_conflict(campaign_id, body.attribute, body.value)
    return _state_dict(svc.get_state(campaign_id))
