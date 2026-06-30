"""Gallery router — screenshots/materials API endpoint (#296)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from applicant.application.services.gallery_service import GalleryService

router = APIRouter(prefix="/api/gallery", tags=["gallery"])


def _get_service(request: Any) -> GalleryService:
    return request.app.state.container.gallery_service


@router.get("/screenshots/{campaign_id}")
def list_screenshots(campaign_id: str, svc: GalleryService = Depends(_get_service)) -> dict[str, Any]:
    return {"screenshots": svc.list_screenshots(campaign_id)}


@router.get("/materials/{campaign_id}")
def list_materials(campaign_id: str, svc: GalleryService = Depends(_get_service)) -> dict[str, Any]:
    return {"materials": svc.list_materials(campaign_id)}
