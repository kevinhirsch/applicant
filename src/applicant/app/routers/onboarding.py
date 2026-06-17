"""Onboarding router — Workday-ready resumable intake (FR-ONBOARD-1/2/3).

Zero-CLI endpoints (NFR-ZEROCLI-1) for the comprehensive intake: get/resume the
state, save a step, complete (gated on required sections), and ingest the base
resume to bootstrap + reconcile the attribute cloud. Gated behind the LLM-settings
gate (FR-UI-5) like the rest of the application surface.
"""

from __future__ import annotations

import re
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

#: Max base-resume upload size (bytes). Bounds an unauthenticated/large upload so a
#: hostile client cannot exhaust memory by streaming a huge body (SECURITY DoS).
#: Module-level so it can be monkeypatched/overridden by config.
MAX_RESUME_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB

#: Suffixes allowed for a base resume; anything else is normalized to ``.txt`` so a
#: crafted filename can never pick the on-disk extension.
_ALLOWED_RESUME_SUFFIXES = {".txt", ".pdf", ".doc", ".docx", ".rtf", ".md"}


def _safe_dest(uploads: Path, leaf: str) -> Path:
    """Resolve ``uploads / leaf`` safely, refusing any path traversal (SECURITY).

    Mirrors the fonts router: the leaf is sanitized to a flat single segment and
    the resolved path's parent is asserted to be the uploads root, so a crafted
    ``campaign_id``/filename like ``../../../../tmp/pwned`` can NEVER write outside
    the confined uploads directory (arbitrary file write).
    """
    sanitized = re.sub(r"[^A-Za-z0-9._-]", "_", leaf).lstrip(".") or "upload"
    uploads_root = uploads.resolve()
    dest = (uploads_root / sanitized).resolve()
    if dest.parent != uploads_root:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid upload name: refusing a path that escapes the uploads dir.",
        )
    return dest


async def _read_capped(file: UploadFile, max_bytes: int) -> bytes:
    """Read an upload body but reject (413) once it exceeds ``max_bytes``.

    Reads in bounded chunks so an over-limit body is rejected WITHOUT ever
    buffering the whole payload in memory (SECURITY DoS).
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(64 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"Upload too large: max {max_bytes} bytes.",
            )
        chunks.append(chunk)
    return b"".join(chunks)


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
    suffix = Path(file.filename or "resume.txt").suffix.lower()
    if suffix not in _ALLOWED_RESUME_SUFFIXES:
        suffix = ".txt"  # allowlist-bound: never trust the uploaded extension
    # SECURITY: sanitize the path-param campaign_id to a flat segment so a
    # traversal value cannot escape the uploads dir (arbitrary file write).
    dest = _safe_dest(uploads, f"{campaign_id}{suffix}")
    body = await _read_capped(file, MAX_RESUME_UPLOAD_BYTES)
    # Reject an empty upload up front (400): a zero-byte file has nothing to parse
    # and would otherwise crash the parser with an opaque 500.
    if not body.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Empty base-resume upload: nothing to parse.",
        )
    dest.write_bytes(body)

    # A corrupt/unparseable file is a client problem, not a server fault: map parser
    # failures to 422 instead of leaking a 500 with a traceback.
    try:
        result = svc.ingest_base_resume(campaign_id, str(dest))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Could not parse the uploaded base resume: {exc}",
        ) from exc
    conflicts = getattr(result, "conflicts", None) or []
    return {
        "auto_applied": getattr(result, "auto_applied", []),
        "attribute_count": getattr(result, "attribute_count", 0),
        "conflicts": [
            {
                "attribute": getattr(c, "attribute", None),
                "interview_value": getattr(c, "interview_value", None),
                "parsed_value": getattr(c, "parsed_value", None),
            }
            for c in conflicts
        ],
        "requires_confirmation": bool(conflicts),
    }


@router.post("/{campaign_id}/confirm-conflict")
def confirm_conflict(
    campaign_id: str, body: ConfirmConflictIn, svc=Depends(get_onboarding_service)
) -> dict:
    """Apply a flagged integral change after explicit confirmation (FR-FB-3)."""
    svc.confirm_conflict(campaign_id, body.attribute, body.value)
    return _state_dict(svc.get_state(campaign_id))
