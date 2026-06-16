"""Fonts router — upload/management flow (FR-FONT-1/2).

Zero-CLI endpoints: report required/missing fonts for an uploaded base resume,
upload a missing font (installed into the confined conversion environment with a
runtime cache refresh), and list installed fonts. Gated behind the LLM gate.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, UploadFile

from applicant.app.deps import get_font_service, require_llm_configured

router = APIRouter(
    prefix="/api/fonts",
    tags=["fonts"],
    dependencies=[Depends(require_llm_configured)],  # FR-UI-5 gate
)


def _report_dict(report) -> dict:
    return {
        "required": report.required,
        "missing": report.missing,
        "installed": report.installed,
    }


@router.get("")
def list_fonts(svc=Depends(get_font_service)) -> dict:
    return {"installed": svc.list_installed()}


@router.post("/detect")
async def detect_required(file: UploadFile = File(...), svc=Depends(get_font_service)) -> dict:
    """Detect required fonts for an uploaded resume + report missing (FR-FONT-1)."""
    uploads = Path(tempfile.gettempdir()) / "applicant_uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    suffix = Path(file.filename or "resume.txt").suffix or ".txt"
    dest = uploads / f"fontdetect{suffix}"
    dest.write_bytes(await file.read())
    return _report_dict(svc.report_for_document(str(dest)))


@router.post("/install")
async def install_font(
    name: str = Form(...),
    file: UploadFile = File(...),
    svc=Depends(get_font_service),
) -> dict:
    """Install an uploaded missing font + refresh cache at runtime (FR-FONT-2)."""
    uploads = Path(tempfile.gettempdir()) / "applicant_uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    suffix = Path(file.filename or f"{name}.ttf").suffix or ".ttf"
    dest = uploads / f"{name}{suffix}"
    dest.write_bytes(await file.read())
    report = svc.install(str(dest), name)
    return {"installed": report.installed, "confirmed": name in report.installed}
