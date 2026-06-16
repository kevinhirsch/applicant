"""Agent-run controls router (FR-AGENT-1/2/7). Gated behind the LLM gate (FR-UI-5).

Configure throughput (clamped to the 30/day hard cap) + run mode, and read the latest
per-run intent sentence. Run records persist to ``agent_runs``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from applicant.app.deps import get_agent_run_service, require_llm_configured
from applicant.core.entities.campaign import THROUGHPUT_HARD_CAP

router = APIRouter(
    prefix="/api/agent-runs", tags=["agent-runs"], dependencies=[Depends(require_llm_configured)]
)


class ConfigureRunIn(BaseModel):
    run_mode: str | None = None  # continuous | fixed_duration | until_n_viable
    throughput_target: int | None = None
    schedule: dict | None = None


@router.put("/{campaign_id}/config")
def configure_run(campaign_id: str, body: ConfigureRunIn, svc=Depends(get_agent_run_service)) -> dict:
    c = svc.configure_run(
        campaign_id,  # type: ignore[arg-type]
        run_mode=body.run_mode,
        throughput_target=body.throughput_target,
        schedule=body.schedule,
    )
    return {
        "campaign_id": c.id,
        "run_mode": c.run_mode.value,
        "throughput_target": c.throughput_target,
        "hard_cap": THROUGHPUT_HARD_CAP,
        "schedule": c.schedule,
    }


@router.get("/{campaign_id}/intent")
def latest_intent(campaign_id: str, svc=Depends(get_agent_run_service)) -> dict:
    return {"campaign_id": campaign_id, "intent": svc.latest_intent(campaign_id)}  # type: ignore[arg-type]


@router.get("/{campaign_id}")
def list_runs(campaign_id: str, svc=Depends(get_agent_run_service)) -> dict:
    runs = svc.list_runs(campaign_id)  # type: ignore[arg-type]
    return {
        "campaign_id": campaign_id,
        "count": len(runs),
        "items": [
            {
                "id": r.id,
                "intent": r.intent_sentence,
                "run_mode": r.run_mode.value,
                "throughput_target": r.throughput_target,
                "stats": r.stats,
            }
            for r in runs
        ],
    }
