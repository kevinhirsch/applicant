"""Campaigns router (FR-CRIT-4). Gated behind the LLM-settings gate (FR-UI-5).

# STAGE B — Phase 1 expands campaign config; the LLM gate is wired here today to
# demonstrate FR-UI-5 (downstream routes return 409 until LLM configured).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from applicant.app.deps import (
    get_campaign_service,
    get_data_lifecycle_service,
    require_llm_configured,
)
from applicant.core.ids import SYSTEM_CAMPAIGN_ID, CampaignId

router = APIRouter(
    prefix="/api/campaigns",
    tags=["campaigns"],
    dependencies=[Depends(require_llm_configured)],  # FR-UI-5 gate
)


class CreateCampaignIn(BaseModel):
    name: str


@router.get("")
def list_campaigns(svc=Depends(get_campaign_service)) -> list[dict]:
    return [{"id": c.id, "name": c.name, "run_mode": c.run_mode.value} for c in svc.list_campaigns()]


@router.post("", status_code=201)
def create_campaign(body: CreateCampaignIn, svc=Depends(get_campaign_service)) -> dict:
    c = svc.create_campaign(body.name)
    return {"id": c.id, "name": c.name}


@router.delete("/{campaign_id}")
def delete_campaign(
    campaign_id: str,
    svc=Depends(get_campaign_service),
    lifecycle=Depends(get_data_lifecycle_service),
) -> dict:
    """Delete a campaign and PURGE all its associated data (#363, FR-CRIT-4, NFR-PRIV-1).

    Cascades the erasure across the stores — résumés/variants, parsed PII, EEO answers,
    generated materials, attributes, the application-scoped children, AND the banked
    credentials — then verifies nothing PII-bearing survives. The reserved system
    campaign (instance secrets) is never deletable here.
    """
    if campaign_id == SYSTEM_CAMPAIGN_ID:
        raise HTTPException(status_code=422, detail="The system campaign cannot be deleted.")
    cid = CampaignId(campaign_id)
    if svc.get_campaign(cid) is None:
        raise HTTPException(status_code=404, detail="No such campaign.")
    result = lifecycle.delete_campaign(cid)
    return {"deleted": True, **result}
