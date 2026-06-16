"""Admin router — tool toggles (FR-UI-4) + debug/observability surface (FR-OBS-2, FR-LOG-3).

# STAGE B — owned by Phase 4. Provides:
#   * Tool registry read + per-tool toggle (FR-UI-4), bound to the ToolRegistry
#     driven port (persisted to tool_settings).
#   * Debug-surface data (FR-OBS-2 / FR-LOG-3 / dormant-surfaces.md §4): logs,
#     per-page screenshots, per-application history, durable-workflow (DBOS) state.
#
# Where a backing store is not yet wired (e.g. log/screenshot stores land later),
# the endpoint returns an explicit ``pending`` marker so the UI grays the panel
# rather than showing dead data as live (FR-UI-2 scaffold-and-gray).
Gated behind the LLM-settings gate (FR-UI-5).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from applicant.app.container import Container
from applicant.app.deps import get_container, require_llm_configured

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_llm_configured)])


@router.get("")
def index() -> dict:
    return {"surface": "admin", "status": "live", "phase": 4}


# === Tool registry / toggles (FR-UI-4) ====================================
@router.get("/tools")
def list_tools(container: Container = Depends(get_container)) -> dict:
    """Return the tool registry for the FR-UI-4 toggle panel."""
    reg = container.tool_registry
    view = reg.registry_view() if hasattr(reg, "registry_view") else [
        {"key": k, "label": k, "enabled": v} for k, v in reg.all_tools().items()
    ]
    return {"tools": view}


@router.post("/tools/{tool_key}")
def toggle_tool(
    tool_key: str, enabled: bool, container: Container = Depends(get_container)
) -> dict:
    """Toggle a tool on/off and persist (FR-UI-4). Enforced at dispatch."""
    reg = container.tool_registry
    if tool_key not in reg.all_tools():
        raise HTTPException(status_code=404, detail=f"Unknown tool '{tool_key}'")
    reg.set_enabled(tool_key, enabled)
    return {"key": tool_key, "enabled": reg.is_enabled(tool_key)}


# === Debug surface (FR-OBS-2 / FR-LOG-3) ===================================
@router.get("/history/{campaign_id}")
def application_history(campaign_id: str, container: Container = Depends(get_container)) -> dict:
    """Per-application history for the debug surface (FR-OBS-2 / FR-LOG-3).

    Reads durable application records straight from storage so history is always
    available (it is the spine of the observability surface).
    """
    apps = container.storage.applications.list_for_campaign(campaign_id)  # type: ignore[arg-type]
    rows = [
        {
            "application_id": a.id,
            "status": a.status.value,
            "role_name": a.role_name,
            "job_title": a.job_title,
            "work_mode": a.work_mode,
            "root_url": a.root_url,
        }
        for a in apps
    ]
    return {"campaign_id": campaign_id, "applications": rows}


@router.get("/outcomes/{application_id}")
def application_outcomes(application_id: str, container: Container = Depends(get_container)) -> dict:
    """Outcome-event trail for one application (submission/conversion, FR-LOG-4)."""
    events = container.storage.outcomes.list_for_application(application_id)  # type: ignore[arg-type]
    return {
        "application_id": application_id,
        "outcomes": [{"type": e.type, "source": e.source.value} for e in events],
    }


@router.get("/workflow/{application_id}")
def workflow_state(application_id: str, container: Container = Depends(get_container)) -> dict:
    """Durable-workflow (DBOS) state for one application (FR-OBS-2 / FR-DUR-1).

    Reports completed idempotent steps and whether the workflow is pending recovery,
    introspected from the durable orchestrator.
    """
    orch = container.orchestrator
    workflow_id = f"application:{application_id}"
    completed = orch.completed_steps(workflow_id) if hasattr(orch, "completed_steps") else []
    pending = (
        workflow_id in orch.recover_pending() if hasattr(orch, "recover_pending") else False
    )
    return {
        "application_id": application_id,
        "workflow_id": workflow_id,
        "completed_steps": completed,
        "pending_recovery": pending,
    }


@router.get("/screenshots/{application_id}")
def application_screenshots(application_id: str) -> dict:
    """Per-page screenshots for the debug surface (FR-OBS-2).

    The application_screenshots store lands with the live prefill/sandbox capture;
    until then this returns ``pending`` so the panel is grayed, not faked (FR-UI-2).
    """
    return {"application_id": application_id, "screenshots": [], "status": "pending"}


@router.get("/logs")
def logs() -> dict:
    """Recent structured logs for the debug surface (FR-LOG-3 / FR-OBS-2).

    The structlog/OTel tail binding lands with the observability stack; returns
    ``pending`` so the UI grays this panel until then (FR-UI-2).
    """
    return {"entries": [], "status": "pending"}
