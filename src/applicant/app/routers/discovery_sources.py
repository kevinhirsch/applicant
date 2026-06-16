"""Discovery-source registry router (FR-DISC-2/5). Gated behind the LLM gate (FR-UI-5).

Lists the per-campaign user-selectable sources with their enable toggle + learned
yield stats, and lets the user toggle a source on/off (persisted to
``discovery_sources``).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from applicant.app.deps import get_discovery_service, require_llm_configured

router = APIRouter(
    prefix="/api/discovery-sources",
    tags=["discovery"],
    dependencies=[Depends(require_llm_configured)],
)


class ToggleSourceIn(BaseModel):
    enabled: bool


@router.get("/{campaign_id}")
def list_sources(campaign_id: str, svc=Depends(get_discovery_service)) -> dict:
    svc.sync_registry(campaign_id)  # type: ignore[arg-type]
    sources = svc.list_sources(campaign_id)  # type: ignore[arg-type]
    return {
        "campaign_id": campaign_id,
        "items": [
            {"source_key": s.source_key, "enabled": s.enabled, "yield_stats": s.yield_stats}
            for s in sources
        ],
    }


@router.put("/{campaign_id}/{source_key}")
def toggle_source(
    campaign_id: str, source_key: str, body: ToggleSourceIn, svc=Depends(get_discovery_service)
) -> dict:
    svc.set_source_enabled(campaign_id, source_key, body.enabled)  # type: ignore[arg-type]
    return {"campaign_id": campaign_id, "source_key": source_key, "enabled": body.enabled}
