"""UI router (FR-UI-1/2/5).

Serves the wizard/digest/review HTML (the wizard starts with the LLM-settings
gate) and exposes the dormant-surface flags so the frontend can gray unwired
surfaces. The wizard is NOT gated (it is how the user opens the gate); digest and
review are dormant placeholders.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from applicant.app.deps import get_container
from applicant.app.static import static_dir
from applicant.dormant import DORMANT_SURFACES

router = APIRouter(tags=["ui"])


def _screen(name: str, container) -> Path:
    return static_dir(container.settings.app_static_dir) / "applicant" / name


@router.get("/", response_class=HTMLResponse)
def root(container=Depends(get_container)):
    """Entry point -> the OOBE wizard (first UI deliverable, FR-UI-5)."""
    return wizard(container)


@router.get("/wizard", response_class=HTMLResponse)
def wizard(container=Depends(get_container)):
    path = _screen("wizard.html", container)
    if path.is_file():
        return FileResponse(str(path))
    return HTMLResponse("<h1>Applicant setup wizard</h1>", status_code=200)


@router.get("/digest", response_class=HTMLResponse)
def digest(container=Depends(get_container)):
    path = _screen("digest.html", container)
    if path.is_file():
        return FileResponse(str(path))
    return HTMLResponse("<h1>Digest (dormant)</h1>", status_code=200)


@router.get("/review", response_class=HTMLResponse)
def review(container=Depends(get_container)):
    path = _screen("review.html", container)
    if path.is_file():
        return FileResponse(str(path))
    return HTMLResponse("<h1>Review (dormant)</h1>", status_code=200)


@router.get("/api/dormant-surfaces")
def dormant_surfaces() -> JSONResponse:
    """Expose the dormant-surface registry so the UI can gray unwired surfaces."""
    return JSONResponse(
        [
            {
                "key": s.key,
                "name": s.surface_name,
                "requirement_ids": list(s.requirement_ids),
                "live_phase": s.live_phase,
                "status": "dormant",
            }
            for s in DORMANT_SURFACES
        ]
    )
