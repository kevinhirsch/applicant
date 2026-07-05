"""Agent-run controls router (FR-AGENT-1/2/7). Gated behind the LLM gate (FR-UI-5).

Configure throughput (clamped to the 30/day hard cap) + run mode, and read the latest
per-run intent sentence. Run records persist to ``agent_runs``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from applicant.app.deps import (
    get_agent_run_service,
    get_scheduler,
    require_automated_work,
    require_llm_configured,
)
from applicant.core.entities.campaign import THROUGHPUT_HARD_CAP

router = APIRouter(
    prefix="/api/agent-runs",
    tags=["agent-runs"],
    dependencies=[Depends(require_llm_configured), Depends(require_automated_work)],
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


@router.get("/{campaign_id}/status")
def run_status(
    campaign_id: str,
    svc=Depends(get_agent_run_service),
    scheduler=Depends(get_scheduler),
) -> dict:
    """Live agent status: per-campaign config + latest intent/stats + today's count,
    plus the scheduler heartbeat (running / last-tick / next-tick) (FR-AGENT-7).

    ``scheduler.campaign`` (dark-engine audit #73) carries THIS campaign's own
    tick failures / overlap-skips, which previously reached only the logs — it is
    omitted entirely when the campaign has never failed or been skipped, so a
    healthy campaign's payload is unchanged.
    """
    out = svc.status(campaign_id)  # type: ignore[arg-type]
    out["scheduler"] = scheduler.state() if scheduler is not None else None
    if scheduler is not None and isinstance(out["scheduler"], dict):
        try:
            health = scheduler.campaign_health(campaign_id)
        except Exception:  # pragma: no cover - defensive: a health read is best-effort
            health = {}
        if health:
            out["scheduler"]["campaign"] = health
    return out


@router.post("/{campaign_id}/run")
def run_now(campaign_id: str, scheduler=Depends(get_scheduler)) -> dict:
    """Run one tick for this campaign immediately (the operator 'Run now').

    No 60s wait: discovers → scores → delivers digest → advances approved pipelines
    one step. Returns the tick result; reports ``ran=False`` if a run is already in
    flight for the campaign or the automated-work conditions aren't met this tick."""
    if scheduler is None:  # pragma: no cover - scheduler is always wired in prod
        return {"campaign_id": campaign_id, "ran": False, "reason": "scheduler unavailable"}
    return scheduler.run_now(campaign_id)


@router.post("/{campaign_id}/pause")
def pause_run(campaign_id: str, svc=Depends(get_agent_run_service)) -> dict:
    """Pause the campaign's automated work (NFR-ZEROCLI-1) — no restart required."""
    c = svc.set_active(campaign_id, False)  # type: ignore[arg-type]
    return {"campaign_id": c.id, "active": c.active, "paused": not c.active}


@router.post("/{campaign_id}/resume")
def resume_run(campaign_id: str, svc=Depends(get_agent_run_service)) -> dict:
    """Resume a paused campaign's automated work (NFR-ZEROCLI-1)."""
    c = svc.set_active(campaign_id, True)  # type: ignore[arg-type]
    return {"campaign_id": c.id, "active": c.active, "paused": not c.active}


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
                # dark-engine audit #75: a "recent runs" mini-table needs a WHEN
                # per row — every run already carries one, it just never left
                # this endpoint.
                "timestamp": r.timestamp.isoformat() if r.timestamp else None,
            }
            for r in runs
        ],
    }
