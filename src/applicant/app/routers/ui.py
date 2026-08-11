"""UI router (FR-UI-1/2/5).

Serves the app's HTML surfaces and exposes the dormant-surface flags so the
frontend can gray unwired surfaces. The root and ``/wizard`` routes serve the
settings page, which on first run opens itself to the setup sections and keeps the
chat surface locked until the model is connected. None of these HTML routes are
gated (they are how the user opens the gate); digest and review are dormant
placeholders.
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
    """Entry point -> the settings page (auto-opens to setup on first run)."""
    return wizard(container)


@router.get("/wizard", response_class=HTMLResponse)
def wizard(container=Depends(get_container)):
    """The settings page; on first run it opens to the setup sections (FR-UI-5)."""
    path = _screen("setup.html", container)
    if path.is_file():
        return FileResponse(str(path))
    return HTMLResponse("<h1>Applicant settings</h1>", status_code=200)


@router.get("/setup", response_class=HTMLResponse)
def setup(container=Depends(get_container)):
    """Explicit alias for the settings/setup page."""
    return wizard(container)


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


@router.get("/criteria", response_class=HTMLResponse)
def criteria(container=Depends(get_container)):
    """Criteria editor surface (FR-CRIT-1/2/3 / FR-FB-3 / FR-UI-6)."""
    path = _screen("criteria.html", container)
    if path.is_file():
        return FileResponse(str(path))
    return HTMLResponse("<h1>Criteria (dormant)</h1>", status_code=200)


@router.get("/attributes", response_class=HTMLResponse)
def attributes(container=Depends(get_container)):
    """Attribute-cloud editor surface (FR-ATTR-1/2/3/4/6 / FR-FB-3 / FR-UI-6)."""
    path = _screen("attributes.html", container)
    if path.is_file():
        return FileResponse(str(path))
    return HTMLResponse("<h1>Attributes (dormant)</h1>", status_code=200)


@router.get("/debug", response_class=HTMLResponse)
def debug(container=Depends(get_container)):
    """Debug / observability surface (FR-OBS-2 / FR-LOG-3 / FR-UI-6)."""
    path = _screen("debug.html", container)
    if path.is_file():
        return FileResponse(str(path))
    return HTMLResponse("<h1>Debug (dormant)</h1>", status_code=200)


@router.get("/chat", response_class=HTMLResponse)
def chat(container=Depends(get_container)):
    """Assistant chatbot surface (FR-CHAT-1 / FR-UI-6)."""
    path = _screen("chat.html", container)
    if path.is_file():
        return FileResponse(str(path))
    return HTMLResponse("<h1>Chat (dormant)</h1>", status_code=200)


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
                "status": s.status,
                "wiring_notes": s.wiring_notes,
            }
            for s in DORMANT_SURFACES
        ]
    )
