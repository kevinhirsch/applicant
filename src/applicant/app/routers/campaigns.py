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


class UpdateCampaignIn(BaseModel):
    """Partial campaign-config update (rename / archive / throughput / budget).

    Every field is optional; only those supplied change. The engine clamps the
    throughput target and exploration budget into their safe ranges server-side
    (FR-AGENT-1 / FR-DISC-5) — a caller cannot push past the safety envelope.
    """

    name: str | None = None
    run_mode: str | None = None
    throughput_target: int | None = None
    exploration_budget: float | None = None
    active: bool | None = None


def _campaign_dict(c) -> dict:
    """Full campaign config the Settings surface renders + edits."""
    return {
        "id": c.id,
        "name": c.name,
        "run_mode": c.run_mode.value,
        "throughput_target": c.throughput_target,
        "exploration_budget": c.exploration_budget,
        "active": c.active,
    }


@router.get("")
def list_campaigns(svc=Depends(get_campaign_service)) -> list[dict]:
    return [_campaign_dict(c) for c in svc.list_campaigns()]


@router.post("", status_code=201)
def create_campaign(body: CreateCampaignIn, svc=Depends(get_campaign_service)) -> dict:
    c = svc.create_campaign(body.name)
    return _campaign_dict(c)


@router.patch("/{campaign_id}")
def update_campaign(
    campaign_id: str, body: UpdateCampaignIn, svc=Depends(get_campaign_service)
) -> dict:
    """Rename / archive / re-tune a campaign (FR-CRIT-4, FR-AGENT-1/2, FR-DISC-5).

    The reserved system campaign (instance secrets) is never editable here.
    """
    if campaign_id == SYSTEM_CAMPAIGN_ID:
        raise HTTPException(status_code=422, detail="The system campaign cannot be edited.")
    cid = CampaignId(campaign_id)
    if svc.get_campaign(cid) is None:
        raise HTTPException(status_code=404, detail="No such campaign.")
    try:
        updated = svc.update_campaign(
            cid,
            name=body.name,
            run_mode=body.run_mode,
            throughput_target=body.throughput_target,
            exploration_budget=body.exploration_budget,
            active=body.active,
        )
    except ValueError as exc:  # bad run_mode value
        raise HTTPException(status_code=422, detail=f"Invalid value: {exc}") from exc
    return _campaign_dict(updated)


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
