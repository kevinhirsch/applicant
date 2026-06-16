"""Campaigns router (FR-CRIT-4). Gated behind the LLM-settings gate (FR-UI-5).

# STAGE B — Phase 1 expands campaign config; the LLM gate is wired here today to
# demonstrate FR-UI-5 (downstream routes return 409 until LLM configured).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from applicant.app.deps import get_campaign_service, require_llm_configured

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
