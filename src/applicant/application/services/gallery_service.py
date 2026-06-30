"""Gallery integration — applicant screenshots/materials as a gallery, engine side.

Issue #296: Provides engine-backed gallery endpoints for screenshots and
generated materials associated with applications.
"""

from __future__ import annotations

from typing import Any

from applicant.observability.logging import get_logger

log = get_logger(__name__)


class GalleryService:
    """Screenshots/materials gallery engine."""

    def __init__(self, storage: Any) -> None:
        self._storage = storage

    def list_screenshots(self, campaign_id: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        try:
            screenshots = self._storage.screenshots.list_for_campaign(campaign_id)
            for s in screenshots:
                out.append({
                    "id": str(s.id),
                    "application_id": str(s.application_id),
                    "url": getattr(s, "url", ""),
                    "caption": getattr(s, "caption", ""),
                    "created_at": str(getattr(s, "created_at", "")),
                })
        except Exception as exc:
            log.debug("gallery_list_failed", error=str(exc))
        return out

    def list_materials(self, campaign_id: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        try:
            docs = self._storage.documents.list_for_campaign(campaign_id)
            for d in docs:
                out.append({
                    "id": str(d.id),
                    "application_id": str(d.application_id),
                    "name": getattr(d, "name", ""),
                    "content_type": getattr(d, "content_type", ""),
                    "created_at": str(getattr(d, "created_at", "")),
                })
        except Exception as exc:
            log.debug("gallery_materials_failed", error=str(exc))
        return out

    def health(self) -> dict[str, Any]:
        return {"available": True}
