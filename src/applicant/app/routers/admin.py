"""Admin router — tool toggles (FR-UI-4) + debug/observability surface (FR-OBS-2, FR-LOG-3).

Phase 4. Provides:
  * Tool registry read + per-tool toggle (FR-UI-4), bound to the ToolRegistry
    driven port (persisted to tool_settings) and enforced at dispatch.
  * Debug-surface data (FR-OBS-2 / FR-LOG-3 / FR-UI-6): recent redacted logs,
    per-application history, per-page screenshots, durable-workflow (DBOS) state,
    and the resume-variant library with lineage / scores / approval state.

All read-models come from the AdminQueryService (real storage + orchestrator +
logging ring buffer). Gated behind the LLM-settings gate (FR-UI-5).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from applicant.app.container import Container
from applicant.app.deps import (
    get_admin_query_service,
    get_container,
    get_learning_service,
    get_storage,
    require_llm_configured,
)

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
def application_history(
    campaign_id: str, limit: int = 200, admin_query=Depends(get_admin_query_service)
) -> dict:
    """Per-application history for the debug surface (FR-OBS-2 / FR-LOG-3 / FR-UI-6).

    Each row carries its logged detail: status, role, work mode, the variant used,
    captured-screenshot count, and recorded outcome events. ``limit`` bounds the rows
    so a long-running campaign's history never returns an unbounded list (#14).
    """
    # #13: clamp the caller-supplied limit on BOTH ends — ``max(0, ...)`` floors a
    # negative ``?limit=-5`` (which would otherwise pass a negative SQL LIMIT) and
    # ``min(..., 1000)`` caps a huge value so it cannot force an unbounded scan.
    rows = admin_query.application_history(
        campaign_id, limit=max(0, min(limit, 1000))  # type: ignore[arg-type]
    )
    return {"campaign_id": campaign_id, "applications": rows}


@router.get("/outcomes/{application_id}")
def application_outcomes(application_id: str, storage=Depends(get_storage)) -> dict:
    """Outcome-event trail for one application (submission/conversion, FR-LOG-4)."""
    events = storage.outcomes.list_for_application(application_id)  # type: ignore[arg-type]
    return {
        "application_id": application_id,
        "outcomes": [{"type": e.type, "source": e.source.value} for e in events],
    }


@router.get("/detections/{campaign_id}")
def application_detections(
    campaign_id: str, admin_query=Depends(get_admin_query_service)
) -> dict:
    """Persisted automation-detection signal history (FR-OBS-2 / FR-PREFILL-6)."""
    events = admin_query.detection_events(campaign_id)  # type: ignore[arg-type]
    return {"campaign_id": campaign_id, "detections": events, "status": "live"}


@router.get("/workflow/{application_id}")
def workflow_state(application_id: str, admin_query=Depends(get_admin_query_service)) -> dict:
    """Durable-workflow (DBOS) state for one application (FR-OBS-2 / FR-DUR-1).

    Reports completed idempotent steps and whether the workflow is pending recovery,
    introspected from the durable orchestrator.
    """
    return admin_query.workflow_state(application_id)  # type: ignore[arg-type]


@router.get("/screenshots/{application_id}")
def application_screenshots(
    application_id: str, admin_query=Depends(get_admin_query_service)
) -> dict:
    """Per-page screenshots for the debug surface (FR-OBS-2).

    Reads the application_screenshots store captured during pre-fill/sandbox runs.
    """
    shots = admin_query.screenshots(application_id)  # type: ignore[arg-type]
    return {"application_id": application_id, "screenshots": shots, "status": "live"}


@router.get("/logs")
def logs(limit: int = 100, admin_query=Depends(get_admin_query_service)) -> dict:
    """Recent structured logs for the debug surface (FR-LOG-3 / FR-OBS-2).

    Tails the structlog ring buffer; entries are already secret-redacted (NFR-PRIV-1).
    """
    # #13: clamp the caller-supplied limit on both ends — ``max(0, ...)`` floors a
    # negative ``?limit=`` and ``min(..., 1000)`` caps the tail size.
    entries = admin_query.logs(max(0, min(limit, 1000)))
    return {"entries": entries, "status": "live"}


@router.get("/variants/{campaign_id}")
def variant_library(campaign_id: str, admin_query=Depends(get_admin_query_service)) -> dict:
    """Resume-variant library: lineage / scores / approval state (FR-UI-6 / FR-RESUME-6)."""
    variants = admin_query.variant_library(campaign_id)  # type: ignore[arg-type]
    return {"campaign_id": campaign_id, "variants": variants}


@router.get("/prefill-diagnostics")
def prefill_diagnostics(container: Container = Depends(get_container)) -> dict:
    """Recent pre-fill silent-degradation diagnostics (dark-engine audit #34).

    ``PrefillService.diagnostics()`` keeps a bounded, deduped ring of plain-
    language operator messages for credential / LLM / login failures that
    degrade gracefully (the pre-fill loop never crashes) — recorded so the
    failure is surfaced rather than lost (#202/#203/#211/#223). Process-global
    (not campaign-scoped), like ``/tools`` and ``/logs`` above.
    """
    pf = container.prefill_service
    entries = pf.diagnostics() if pf is not None else []
    return {"diagnostics": entries, "status": "live"}


@router.get("/stuck-applications/{campaign_id}")
def stuck_applications(campaign_id: str, container: Container = Depends(get_container)) -> dict:
    """Applications the loop has given up re-driving (dark-engine audit #62).

    After ``_RESUME_FAILURE_CAP`` consecutive failed resumes the loop stops
    re-driving an application and fires ONE deduped notification — but until now
    nothing could LIST the give-up set, so a silently-stuck application was
    invisible except for that one notification. Reads the SAME process-lived
    ``ResumeLedger`` the running scheduler writes to (``AgentLoop.list_given_up``),
    so this always reflects the live loop state, not a stale snapshot. Returns an
    empty list (never an error) when the loop is not wired (e.g. no orchestrator).
    """
    loop = container.agent_loop
    rows = loop.list_given_up(campaign_id) if loop is not None else []  # type: ignore[arg-type]
    return {"campaign_id": campaign_id, "applications": rows, "status": "live"}


@router.post("/stuck-applications/{application_id}/retry")
def retry_stuck_application(
    application_id: str, container: Container = Depends(get_container)
) -> dict:
    """Clear one application's give-up flag so the loop re-drives it (#62).

    Previously the ONLY way to unstick a given-up application was a full process
    restart (which rebuilds a fresh, empty ``ResumeLedger``) — silently forgetting
    every OTHER application's failure/backoff state too. This clears just the one
    application's entry in the same process-lived ledger the loop reads every
    tick, so the very next tick re-drives it. 404s when the application was not
    actually in the give-up set (nothing to retry).
    """
    loop = container.agent_loop
    cleared = loop.retry_given_up(application_id) if loop is not None else False  # type: ignore[arg-type]
    if not cleared:
        raise HTTPException(status_code=404, detail="No such stuck application.")
    return {"application_id": application_id, "retried": True}


@router.get("/learning/{campaign_id}")
def learning_insights(campaign_id: str, learning=Depends(get_learning_service)) -> dict:
    """What the system has learned for a campaign, in plain language (FR-LEARN-5/6).

    A read-only operator-visibility view: the conversion totals across all sources,
    each source's funnel (matched -> approved -> submitted) ranked by how well it
    converts, the roles that actually convert, and the exploration budget. Built
    purely from persisted learning state (no LLM, no secrets) so the operator can
    see and trust the bias the engine applies.
    """
    return learning.build_summary(campaign_id)  # type: ignore[arg-type]


# === Stealth honesty + egress (FR-STEALTH-4 / FR-STEALTH-5) ================
@router.get("/stealth")
def stealth(container: Container = Depends(get_container)) -> dict:
    """Surface the honest best-effort stealth caveat + the live egress posture.

    FR-STEALTH-5: the caveat is shown to the user (here + in the debug UI) so the
    best-effort honesty note is never hidden. FR-STEALTH-4: report the configured
    egress mode and whether a residential proxy is actually threaded into launch.
    """
    from applicant.adapters.browser.stealth import EGRESS_CAVEAT, STEALTH_CAVEAT

    egress = getattr(container.browser, "egress", None)
    return {
        "caveat": STEALTH_CAVEAT,
        "egress_caveat": EGRESS_CAVEAT,
        "egress": {
            "mode": getattr(egress, "mode", "direct"),
            "is_direct_residential": getattr(egress, "is_direct_residential", True),
            "proxy_configured": bool(getattr(egress, "proxy_url", None)),
        },
        "status": "live",
    }
