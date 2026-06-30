"""Compare router — cross-entity comparison API endpoint.

Issue #297: Backs the present-but-disabled Compare surface (#184).
Provides /api/compare endpoint for comparing applications and postings.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from applicant.application.services.compare_service import CompareService

router = APIRouter(prefix="/api/compare", tags=["compare"])


def _get_service(request: Any) -> CompareService:
    container = request.app.state.container
    return container.compare_service


@router.post("/applications")
def compare_applications(
    application_ids: list[str],
    campaign_id: str | None = None,
    svc: CompareService = Depends(_get_service),
) -> dict[str, Any]:
    result = svc.compare_applications(application_ids, campaign_id)
    return {
        "entity_ids": result.entity_ids,
        "entity_labels": result.entity_labels,
        "dimensions": [
            {"key": d.key, "label": d.label, "values": d.values, "diff": d.diff}
            for d in result.dimensions
        ],
        "summary": result.summary,
    }


@router.post("/postings")
def compare_postings(
    posting_ids: list[str],
    campaign_id: str | None = None,
    svc: CompareService = Depends(_get_service),
) -> dict[str, Any]:
    result = svc.compare_postings(posting_ids, campaign_id)
    return {
        "entity_ids": result.entity_ids,
        "entity_labels": result.entity_labels,
        "dimensions": [
            {"key": d.key, "label": d.label, "values": d.values, "diff": d.diff}
            for d in result.dimensions
        ],
        "summary": result.summary,
    }
