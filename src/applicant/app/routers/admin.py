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

import dataclasses
import mimetypes
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from applicant.app.container import Container
from applicant.app.deps import (
    get_admin_query_service,
    get_container,
    get_data_lifecycle_service,
    get_learning_service,
    get_setup_service,
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


@router.get("/screenshots/{application_id}/{screenshot_id}/image")
def application_screenshot_image(
    application_id: str, screenshot_id: str, admin_query=Depends(get_admin_query_service)
) -> FileResponse:
    """Raw image bytes for one captured screenshot (FR-OBS-2, dark-engine audit #28).

    ``page_ref`` is a ``file://`` ref into the sandbox's local capture directory
    (FR-LOG-2) — this streams the bytes so the debug surface can render the real
    proof-of-work image instead of just a filename label. 404s when the id is
    unknown, the ref isn't a real local file (e.g. the deterministic
    ``screenshot://fake`` ref used by the in-memory sandbox in tests), or the
    file no longer exists on disk (ephemeral capture dir, reclaimed after a
    restart) — never fabricates image bytes.
    """
    shots = admin_query.screenshots(application_id)  # type: ignore[arg-type]
    match = next((s for s in shots if s.get("id") == screenshot_id), None)
    if match is None:
        raise HTTPException(status_code=404, detail="Screenshot not found")
    parsed = urlparse(match.get("page_ref") or "")
    if parsed.scheme != "file" or not parsed.path:
        raise HTTPException(status_code=404, detail="No image bytes available for this screenshot")
    path = Path(parsed.path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Screenshot image is no longer available")
    media_type = mimetypes.guess_type(path.name)[0] or "image/png"
    return FileResponse(str(path), media_type=media_type)


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


@router.get("/routines")
def induced_routines(container: Container = Depends(get_container)) -> dict:
    """Induced per-ATS routines, the AWM self-improvement flywheel's memory of what
    worked (#306, dark-engine audit #45).

    After a successful pre-fill page on a given ATS the loop induces a reusable
    routine (``PrefillService._induce_routine`` -> ``LearningService.induce_workflow``)
    keyed by domain; the SAME process-lived ``RoutineStore`` offers it back as a
    planning prior the next time that domain is seen. This is the plain read-only
    overview of every domain the loop has learned a routine for — process-global (not
    campaign-scoped), like ``/prefill-diagnostics`` / ``/lessons`` above. Each row is
    ``domain``, ``step_count``, ``successes``/``failures``, the net ``score`` used for
    ACE pruning, and ``source``. Returns an empty list (never an error) when the
    pre-fill service or its routine store is not wired.
    """
    pf = container.prefill_service
    routines = pf.list_routines() if pf is not None else []
    return {"routines": routines, "status": "live"}


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


@router.get("/resume-status/{application_id}")
def resume_status(application_id: str, container: Container = Depends(get_container)) -> dict:
    """Countdown to the next resume attempt for one blocked application
    (dark-engine audit #78).

    Reads the SAME process-lived ``ResumeLedger`` the running scheduler writes to
    (``AgentLoop.resume_backoff_status``), so a just-resolved blocker (a missing
    detail saved, a question answered, a redline approved) can tell the user
    honestly when the loop will actually pick the application back up, instead of
    the up-to-5-minute silence the fixed resume backoff otherwise leaves. Returns
    ``{"status": "not_blocked"}`` (never a 404) when the application isn't
    currently backed off, so a caller can poll this defensively right after
    resolving a blocker without special-casing "nothing to show".
    """
    loop = container.agent_loop
    status = loop.resume_backoff_status(application_id) if loop is not None else None  # type: ignore[arg-type]
    if status is None:
        return {"application_id": application_id, "status": "not_blocked"}
    return {"application_id": application_id, **status}


@router.get("/research-provenance/{application_id}")
def research_provenance(
    application_id: str, admin_query=Depends(get_admin_query_service)
) -> dict:
    """Which company research (if any) informed one application's materials
    (dark-engine audit #76).

    Reads the checkpointed ``material`` pipeline step for this application's
    durable workflow (``AdminQueryService.research_provenance``) -- a single-app
    sibling of ``/history/{campaign_id}``'s per-row field, reachable from the
    redline review surface (pre-submission, while the checkpoint is still live)
    rather than only from the post-submission per-campaign history. Returns
    ``{"used": false}`` (never a 404) when research was never used for this
    application, its checkpoint has already been cleared (submitted/archived),
    or the orchestrator backend doesn't support step introspection.
    """
    provenance = admin_query.research_provenance(application_id)  # type: ignore[arg-type]
    if provenance is None:
        return {"application_id": application_id, "used": False}
    return {"application_id": application_id, "used": True, **provenance}


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


# === Reflexion failure lessons (FR-LEARN-*, dark-engine audit #44) =========
@router.get("/lessons")
def all_lessons(learning=Depends(get_learning_service)) -> dict:
    """Every verbal Reflexion lesson recorded so far, grouped by ATS (#44).

    ``LearningService.reflect_on_failure`` distills a short natural-language
    lesson from a real pre-fill field failure; the pre-fill loop calls
    ``recall_lessons`` for the SAME ats before its next fill attempt on that
    ATS. This is the plain read-only overview across every domain the loop has
    learned something about, process-global (not campaign-scoped) like
    ``/prefill-diagnostics`` above.
    """
    grouped = learning.list_all_lessons()  # type: ignore[attr-defined]
    return {
        "lessons": {
            ats: [dataclasses.asdict(lesson) for lesson in items]
            for ats, items in grouped.items()
        },
        "status": "live",
    }


@router.get("/lessons/{ats}")
def lessons_for_ats(ats: str, learning=Depends(get_learning_service)) -> dict:
    """Verbal Reflexion lessons recalled for ONE ATS (#44).

    The same read the pre-fill loop performs before a fill attempt on ``ats``
    — surfaced here so an operator can see exactly what the loop already
    knows about a given ATS before/while it runs.
    """
    lessons = learning.recall_lessons(ats)  # type: ignore[arg-type]
    return {
        "ats": ats,
        "lessons": [dataclasses.asdict(lesson) for lesson in lessons],
        "status": "live",
    }


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


# === Engine <-> workspace bridge health (dark-engine audit #71) ============
@router.get("/workspace-bridge")
def workspace_bridge(container: Container = Depends(get_container)) -> dict:
    """Is the engine -> workspace callback channel configured and reachable?

    ``APPLICANT_INTERNAL_TOKEN`` gates calendar-interview sync, deep-research, and
    the memory/skills bridge (``HttpWorkspaceClient``) — a missing or wrong token
    silently disables all three with nothing telling the operator why. This never
    fabricates reachability from config alone: when a token IS configured it calls
    the SAME ``ping`` the client exists for (and the workspace already serves) to
    prove the channel actually round-trips, not just that a secret is set.
    """
    from applicant.ports.driven.workspace import WorkspaceError

    workspace = container.workspace
    configured = bool(workspace.available()) if workspace is not None else False
    if not configured:
        return {"configured": False, "reachable": False, "detail": None, "status": "live"}
    try:
        workspace.ping()
        reachable, detail = True, None
    except WorkspaceError as exc:
        reachable, detail = False, str(exc)
    except Exception as exc:  # pragma: no cover - defensive: never break the status read
        reachable, detail = False, str(exc)
    return {"configured": True, "reachable": reachable, "detail": detail, "status": "live"}


# === Captcha handling status (dark-engine audit #67) =======================
@router.get("/captcha-status")
def captcha_status(container: Container = Depends(get_container)) -> dict:
    """Effective captcha-handling strategy + any real solve/avoid/handoff telemetry.

    ``CAPTCHA_STRATEGY`` (item #83) decides whether captchas hand off to the
    human, are avoided via stealth, or are solved by a paid third-party
    service — but nothing previously reported which is actually configured, or
    whether it's doing anything. The composite solver (``CaptchaSolver``) is
    only built for a non-default strategy (``container.py``'s
    ``_build_captcha_solver`` — the shipped ``human`` default leaves pre-fill's
    captcha handling unwired so every captcha still hands off byte-for-byte as
    today), so this always reports the CONFIGURED strategy from settings, plus
    — only when a solver is actually wired — its real, process-lived
    attempt/outcome counters. Never fabricates a solved/avoided/handed-off
    count: with the default strategy those fields are simply absent.
    """
    settings = container.settings
    pf = container.prefill_service
    solver = pf.captcha_solver if pf is not None else None
    body = {
        "strategy": settings.captcha_strategy,
        "service": settings.captcha_service,
        "key_configured": bool(settings.captcha_api_key),
        "active": solver is not None,
    }
    if solver is not None and hasattr(solver, "stats"):
        body.update(solver.stats())
    return {**body, "status": "live"}


# === Sandbox capacity pacing (dark-engine audit #72) =======================
@router.get("/capacity")
def capacity(container: Container = Depends(get_container)) -> dict:
    """How many applications hold a live sandbox slot vs. wait for one.

    ``CapacityService`` admits/defers a sandbox slot for every application every
    tick (the concurrency cap + pivot-around-blocker), but a deferred admission
    previously only logged ``sandbox_admission_deferred`` with no operator-
    visible surface. Reads the SAME ``SANDBOX_QUEUE`` the live scheduler drives,
    so this always reflects the current queue, not a stale snapshot.
    """
    svc = container.capacity_service
    if svc is None:
        return {
            "active": [],
            "waiting": [],
            "active_count": 0,
            "waiting_count": 0,
            "supported": False,
            "status": "live",
        }
    state = svc.sandbox_queue_state()
    return {
        "active": state["active"],
        "waiting": state["waiting"],
        "active_count": len(state["active"]),
        "waiting_count": len(state["waiting"]),
        "supported": state["supported"],
        "status": "live",
    }


# === Embedding backend disclosure (dark-engine audit #79) ==================
@router.get("/embedding-backend")
def embedding_backend(container: Container = Depends(get_container)) -> dict:
    """Which embedding backend powers memory/dedup matching, and its quality tier.

    ``LocalEmbedding`` is a deterministic offline hashing-trick backend (no
    model download); a real model-backed adapter would implement the same
    ``EmbeddingPort`` and disclose itself the same way via ``describe()``. Read-
    only, plain-language — never claims a quality the active backend doesn't
    have.
    """
    emb = container.embedding
    describe = getattr(emb, "describe", None)
    if callable(describe):
        info = describe()
    else:
        info = {
            "backend": type(emb).__name__ if emb is not None else "none",
            "quality_tier": "unknown",
            "model_backed": False,
            "detail": "",
        }
    return {**info, "status": "live"}


# === PII-retention sweep, on demand (dark-engine audit #37) ================
@router.post("/retention/prune")
def run_retention_sweep(
    days: int | None = None,
    container: Container = Depends(get_container),
    svc=Depends(get_setup_service),
    data_lifecycle=Depends(get_data_lifecycle_service),
) -> dict:
    """Run the PII-retention sweep right now and return the real result (#37).

    ``DataLifecycleService.prune_pii_older_than`` (#363) was previously reachable
    ONLY from the dormant scheduler tick -- there was no way for an operator to
    run a sweep on demand or see what the last one actually removed. This runs
    the SAME cascade synchronously (parsed PII / EEO answers + onboarding
    intakes older than the window) and returns the real per-store pruned counts,
    not a fabricated summary.

    The window defaults to the CURRENTLY persisted Settings > Automation
    retention days (``SetupService.get_automation_prefs()``), falling back to
    the env-sourced ``Settings`` default when nothing has been saved yet --
    mirroring exactly what a scheduled sweep would use today. An explicit
    ``?days=`` overrides it for this one run only and is NOT persisted. A
    window of 0 (the default, "keep forever") is a legitimate no-op: the result
    reports ``skipped: true`` and zero pruned rather than erroring.
    """
    settings = container.settings
    stored = svc.get_automation_prefs()
    default_days = stored.get("pii_retention_days", settings.pii_retention_days)
    effective_days = default_days if days is None else days
    result = data_lifecycle.prune_pii_older_than(days=effective_days)
    result["requested_days"] = effective_days
    return result
