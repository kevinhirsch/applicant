"""Fonts router — upload/management flow (FR-FONT-1/2).

Zero-CLI endpoints: report required/missing fonts for an uploaded base resume,
upload a missing font (installed into the confined conversion environment with a
runtime cache refresh), and list installed fonts. Gated behind the LLM gate.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from applicant.app.deps import get_font_service, require_llm_configured

router = APIRouter(
    prefix="/api/fonts",
    tags=["fonts"],
    dependencies=[Depends(require_llm_configured)],  # FR-UI-5 gate
)

#: Max font/resume upload size (bytes). Bounds the upload body so a hostile client
#: cannot exhaust memory by streaming a huge payload (SECURITY DoS). Module-level
#: so it can be monkeypatched/overridden by config.
MAX_FONT_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB


async def _read_capped(file: UploadFile, max_bytes: int) -> bytes:
    """Read an upload body but reject (413) once it exceeds ``max_bytes``.

    Reads in bounded chunks so an over-limit body is rejected WITHOUT buffering
    the whole payload in memory (SECURITY DoS).
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


def _report_dict(report) -> dict:
    return {
        "required": report.required,
        "missing": report.missing,
        "installed": report.installed,
    }


def _safe_dest(uploads: Path, leaf: str) -> Path:
    """Resolve ``uploads / leaf`` safely, refusing any path traversal (FR-FONT).

    The leaf is sanitized to a flat, single-segment name (no separators / dotted
    escapes) and the resolved path is asserted to stay under the uploads dir, so a
    crafted ``name``/filename like ``../../../../tmp/pwned`` can NEVER write outside
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


@router.get("")
def list_fonts(svc=Depends(get_font_service)) -> dict:
    return {"installed": svc.list_installed()}


@router.post("/detect")
async def detect_required(file: UploadFile = File(...), svc=Depends(get_font_service)) -> dict:
    """Detect required fonts for an uploaded resume + report missing (FR-FONT-1)."""
    uploads = Path(tempfile.gettempdir()) / "applicant_uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    suffix = Path(file.filename or "resume.txt").suffix or ".txt"
    dest = _safe_dest(uploads, f"fontdetect{suffix}")
    dest.write_bytes(await _read_capped(file, MAX_FONT_UPLOAD_BYTES))
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
    dest = _safe_dest(uploads, f"{name}{suffix}")
    dest.write_bytes(await _read_capped(file, MAX_FONT_UPLOAD_BYTES))
    report = svc.install(str(dest), name)
    return {"installed": report.installed, "confirmed": name in report.installed}
