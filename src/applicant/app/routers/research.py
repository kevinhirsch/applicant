"""Research router (Lane B, Stage 2.5) — manual deep-research trigger.

The autonomous agent auto-escalates to deep research on a knowledge gap (wired in
``AgentLoop`` via ``ResearchService``). This router is the *explicit*,
user-initiated counterpart: the UI / assistant can request a research run for a
campaign and read the stored report. It runs the SAME capped/deduped/cached path
(``ResearchService.run_for_campaign``) so a manual run also respects the
per-campaign budget and reuses cached reports for free.

Gated behind the LLM-settings gate (FR-UI-5). The owner is taken from the
authenticated request attribution (single-user engine today), never the body, and
forwarded to the workspace so the run is owner-scoped end to end.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from applicant.app.deps import (
    get_research_service,
    get_storage,
    require_llm_configured,
)
from applicant.core.ids import CampaignId

router = APIRouter(
    prefix="/api/research",
    tags=["research"],
    dependencies=[Depends(require_llm_configured)],  # FR-UI-5 gate
)


class ResearchRequestIn(BaseModel):
    query: str
    company: str | None = None
    role: str | None = None
    context: str | None = None
    max_time: int | None = None
    #: Re-run even when a cached report exists (still charged against the cap).
    force: bool = False


def _require_campaign(storage, campaign_id: str):
    campaign = storage.campaigns.get(CampaignId(campaign_id))
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign


@router.post("/{campaign_id}/run")
def run_research(
    campaign_id: str,
    body: ResearchRequestIn,
    svc=Depends(get_research_service),
    storage=Depends(get_storage),
) -> dict:
    """Run (or reuse) deep research for a campaign — the manual trigger.

    Returns the structured report. When the workspace channel is unavailable or the
    per-campaign budget is exhausted, returns a 200 with ``unavailable: true`` and a
    ``reason`` (the channel being off is a degraded state, not a server error).
    """
    if not (body.query or "").strip():
        raise HTTPException(status_code=422, detail="query must not be empty")
    _require_campaign(storage, campaign_id)
    report = svc.run_for_campaign(
        campaign_id,
        body.query,
        company=body.company,
        role=body.role,
        context=body.context,
        max_time=body.max_time,
        force=body.force,
    )
    return {
        "campaign_id": campaign_id,
        "budget_remaining": svc.budget_remaining(campaign_id),
        **report.to_dict(),
    }


@router.get("/{campaign_id}/cached")
def cached_research(
    campaign_id: str,
    query: str,
    svc=Depends(get_research_service),
    storage=Depends(get_storage),
) -> dict:
    """Read an already-cached report for free — no fresh run, no budget spent.

    404 when nothing is cached yet for this exact (campaign, query); the
    caller should fall back to ``POST .../run`` for a fresh, budget-charged
    run in that case.
    """
    if not (query or "").strip():
        raise HTTPException(status_code=422, detail="query must not be empty")
    _require_campaign(storage, campaign_id)
    report = svc.cached_report(campaign_id, query)
    if report is None:
        raise HTTPException(status_code=404, detail="No cached report for this query")
    data = report.to_dict()
    data["cached"] = True  # the stored copy carries cached=False; this read is the cache hit
    return {
        "campaign_id": campaign_id,
        "budget_remaining": svc.budget_remaining(campaign_id),
        **data,
    }


@router.get("/{campaign_id}/budget")
def research_budget(
    campaign_id: str,
    svc=Depends(get_research_service),
    storage=Depends(get_storage),
) -> dict:
    """Report the campaign's research budget + channel availability."""
    _require_campaign(storage, campaign_id)
    return {
        "campaign_id": campaign_id,
        "available": svc.available(),
        "calls_made": svc.calls_made(campaign_id),
        "budget_remaining": svc.budget_remaining(campaign_id),
    }
