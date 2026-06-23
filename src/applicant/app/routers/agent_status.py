"""Agent live-status router (FR-AGENT-7 / FR-OBS-2 / FR-UI).

A single, read-only, plain-language snapshot of "what the agent is doing" — the
visual complement to the chat track's self-reporting. It assembles three views,
FRESH per request, from the existing read-only state sources (it owns no state of
its own and mutates nothing):

* ``now``   — am I running a tick right now, idle, or paused; today's applied
  count vs the daily budget (Scheduler ``state`` + AgentRunService ``status``);
* ``next``  — the single-sentence next-action intent (FR-AGENT-7), the estimated
  next-tick time, and how many items are waiting on the user (PendingActions);
* ``recent`` — the last few applications / outcomes (AdminQuery
  ``application_history``).

Every source is wrapped defensively: a missing or erroring one contributes
nothing rather than fabricating activity (FR-AGENT-5). The router is gated like
the other agent surfaces (LLM configured + automated-work) and is per-campaign,
mirroring ``/api/agent-runs/{campaign_id}/status`` which the chat track reads.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from applicant.app.deps import (
    get_admin_query_service,
    get_agent_run_service,
    get_pending_actions_service,
    get_scheduler,
    require_automated_work,
    require_llm_configured,
)

router = APIRouter(
    prefix="/api/agent",
    tags=["agent-status"],
    dependencies=[Depends(require_llm_configured), Depends(require_automated_work)],
)

#: How many recent applications to surface in ``recent`` — a short, scannable tail.
RECENT_LIMIT = 5


def _scheduler_state(scheduler) -> dict:
    """Scheduler heartbeat, or an empty dict when unavailable (defensive)."""
    if scheduler is None:
        return {}
    try:
        state = scheduler.state()
        return state if isinstance(state, dict) else {}
    except Exception:  # pragma: no cover - defensive: a bad source contributes nothing
        return {}


def _run_status(svc, campaign_id: str) -> dict:
    """Per-campaign run status, or an empty dict when unavailable (defensive)."""
    try:
        status = svc.status(campaign_id)  # type: ignore[arg-type]
        return status if isinstance(status, dict) else {}
    except Exception:
        return {}


def _pending_count(svc, campaign_id: str) -> int | None:
    """How many items await the user, or ``None`` when the source can't answer."""
    try:
        items = svc.list_pending(campaign_id)  # type: ignore[arg-type]
        return len(items) if items is not None else 0
    except Exception:
        return None


def _recent_applications(svc, campaign_id: str) -> list[dict]:
    """The last few applications/outcomes the engine returns; [] on error."""
    if svc is None:
        return []
    try:
        rows = svc.application_history(campaign_id, limit=RECENT_LIMIT)  # type: ignore[arg-type]
    except TypeError:  # pragma: no cover - older signature without ``limit``
        try:
            rows = svc.application_history(campaign_id)[:RECENT_LIMIT]  # type: ignore[arg-type]
        except Exception:
            return []
    except Exception:
        return []
    if not isinstance(rows, list):
        return []
    return [r for r in rows if isinstance(r, dict)]


def _is_running(sched: dict, status: dict) -> bool:
    """Live only when the scheduler is ticking AND the campaign isn't paused."""
    running = bool(sched.get("running"))
    paused = bool(status.get("paused"))
    return running and not paused


def _now_sentence(running: bool, paused: bool, status: dict) -> str:
    """First-person, plain-language 'what I'm doing now' (no fabrication)."""
    applied = status.get("applied_today")
    budget = status.get("daily_budget")
    tail = ""
    if isinstance(applied, int) and isinstance(budget, int) and budget > 0:
        tail = f" I've started {applied} of today's {budget} applications."
    if paused:
        return "Right now I'm paused, so I'm not starting any new work." + tail
    if running:
        return "Right now I'm working on your job search." + tail
    return "Right now I'm idle, waiting for my next scheduled run." + tail


def _next_sentence(intent: str | None) -> str:
    """First-person 'what's next', preferring the FR-AGENT-7 intent sentence."""
    if intent and str(intent).strip():
        return f"Next I'll {_lower_first(str(intent).strip())}"
    return "Next I'll continue scanning for roles on my schedule."


def _lower_first(text: str) -> str:
    """Lowercase only the first character so the intent reads after 'Next I'll '."""
    return text[:1].lower() + text[1:] if text else text


@router.get("/status/{campaign_id}")
def agent_status(
    campaign_id: str,
    run_svc=Depends(get_agent_run_service),
    scheduler=Depends(get_scheduler),
    pending_svc=Depends(get_pending_actions_service),
    admin_svc=Depends(get_admin_query_service),
) -> dict:
    """A consolidated, plain-language snapshot of the agent's activity.

    Returns ``now`` / ``next`` / ``recent`` blocks assembled fresh from the live
    read-only sources, each wrapped so a failing source omits its contribution
    rather than inventing activity (FR-AGENT-5).
    """
    sched = _scheduler_state(scheduler)
    status = _run_status(run_svc, campaign_id)
    running = _is_running(sched, status)
    paused = bool(status.get("paused"))

    now_block: dict = {
        "running": running,
        "paused": paused,
        "sentence": _now_sentence(running, paused, status),
    }
    if isinstance(status.get("applied_today"), int):
        now_block["applied_today"] = status["applied_today"]
    if isinstance(status.get("daily_budget"), int):
        now_block["daily_budget"] = status["daily_budget"]
    if status.get("run_mode"):
        now_block["run_mode"] = status["run_mode"]
    if status.get("last_run_at"):
        now_block["last_run_at"] = status["last_run_at"]

    intent = status.get("latest_intent")
    next_block: dict = {"sentence": _next_sentence(intent)}
    if intent:
        next_block["intent"] = intent
    if sched.get("next_tick"):
        next_block["next_tick"] = sched["next_tick"]
    pending = _pending_count(pending_svc, campaign_id)
    if pending is not None:
        next_block["pending_actions"] = pending

    recent = _recent_applications(admin_svc, campaign_id)

    return {
        "campaign_id": campaign_id,
        "now": now_block,
        "next": next_block,
        "recent": recent,
    }
