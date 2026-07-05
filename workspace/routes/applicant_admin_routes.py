# routes/applicant_admin_routes.py
"""Applicant Debug / Activity surface ↔ engine bridge (crit-ops lane).

The workspace's *Activity* surface is a read-only debug/observability window onto
the Applicant **engine** (`http://api:8000`): per-application history, per-page
screenshots, redacted run logs, durable-workflow state, the resume-variant
library, and the honest stealth/egress posture. It also exposes the one closing
of the conversion-learning loop the engine cannot do on its own for manual or
hand-off submissions: *mark an application as submitted* (and re-run automatic
submission detection) so a user-completed application still teaches the system.

Every endpoint is a thin, auth-protected proxy over
:class:`src.applicant_engine.ApplicantEngineClient`. The browser never reaches
the engine directly, and every engine failure is normalised to a clean HTTP
response so the surface degrades gracefully instead of throwing.

Scoping: most of this file is an operator/admin surface — application history
and raw logs are operator-grade detail, so they require an admin account (and
an authenticated session in every mode). In single-user / unconfigured mode
there is no admin distinction, so the lone owner sees them (matching the rest
of the workspace). A few reads that are genuinely the owner's OWN data (not
operator detail) get a SEPARATE owner-reachable lane instead — see "owner-
reachable lane" below.

This file is ADDITIVE and disjoint from the other ``applicant_*`` proxies: it
mounts its own ``/api/applicant/admin`` prefix and leaves them untouched. It does
NOT edit the shared engine client beyond the append-only methods that lane added
(``admin_*`` / ``outcome_*``).

Owner-scoped reachability (dark-engine audit B4 items 29/30/32): everything
above requires an admin account even though, on this single-tenant deployment,
every byte belongs to the one owner. Durable-workflow state (item 29) and the
per-application audit-log export (item 30) are genuinely the owner's OWN
data, so they get an owner-reachable lane too, added below under their own
paths -- the existing admin-gated routes above are untouched. Owner-scoping
mirrors ``applicant_campaigns_routes._owner_campaign_ids`` /
``applicant_tracker_routes._owner_application_ids`` elsewhere in this
workspace: the engine itself has no owner concept, so a caller-supplied
``application_id`` is validated against THIS request's own campaign fan-out
(never trusted on its own) before any read or download is forwarded.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from src.applicant_engine import ApplicantEngineClient, EngineError
from src.auth_helpers import get_current_user, is_trusted_loopback, require_user

logger = logging.getLogger(__name__)


# --- request bodies ---------------------------------------------------------


class MarkSubmittedIn(BaseModel):
    attributes_used: dict | None = None


class ToggleToolIn(BaseModel):
    enabled: bool


# --- helpers ----------------------------------------------------------------


def _require_admin(request: Request) -> str:
    """Require an authenticated admin (or the lone owner in single-user mode).

    Application history + raw logs are operator-grade detail, so callers must be
    an admin. In unconfigured / single-user mode (no auth manager, or the manager
    reports no configured users) there is no admin distinction — the lone owner
    is allowed, mirroring the rest of the workspace.
    """
    owner = get_current_user(request)
    auth_mgr = getattr(request.app.state, "auth_manager", None)
    configured = bool(getattr(auth_mgr, "is_configured", False)) if auth_mgr else False

    if not configured:
        # Single-user / first-run: no admin distinction — but the operator-grade
        # surface must still be reachable only from the box itself, not from the
        # network (#228). Unlike require_user, the old gate returned "" for ANY
        # host, so a remote unauthenticated caller passed during setup. Allow the
        # lone owner only from a DIRECT loopback connection — never one merely
        # tunneled/forwarded through something that itself connects to us from
        # loopback (cloudflared, a reverse proxy) — see
        # ``src.auth_helpers.is_trusted_loopback``.
        if owner:
            return owner
        if is_trusted_loopback(request):
            return ""
        raise HTTPException(status_code=401, detail="Not authenticated")

    if not owner:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        is_admin = bool(auth_mgr.is_admin(owner))
    except Exception:  # defensive: never 500 the gate itself
        is_admin = False
    if not is_admin:
        raise HTTPException(status_code=403, detail="This view is available to admins only.")
    return owner


def _engine_http_error(exc: EngineError) -> HTTPException:
    """Translate a typed :class:`EngineError` into an HTTPException for a *write*.

    A transport-level failure (timeout / connection refused — no response) means
    the engine is unreachable → 503. 4xx responses from the engine are forwarded
    (client-correctable: 409 gate, 422 validation, 404 not-found). 5xx responses
    are scrubbed — the raw detail may contain internal stack traces or state; we
    log it server-side and return a generic message to the browser.
    """
    if exc.status is None:
        return HTTPException(
            status_code=503,
            detail="The Applicant engine is unavailable right now. Please try again shortly.",
        )
    if exc.status >= 500:
        logger.warning("engine 5xx (admin): status=%s detail=%s", exc.status, exc.detail or exc.message)
        return HTTPException(status_code=502, detail="The Applicant engine returned an error.")
    detail = exc.detail if exc.detail not in (None, "") else exc.message
    return HTTPException(status_code=exc.status, detail=detail)


async def _owner_application_ids(engine: ApplicantEngineClient) -> "set[str] | None":
    """The application ids that belong to the caller's OWN campaigns, or
    ``None`` when the campaign list itself could not be resolved (engine
    unreachable) — dark-engine audit items 29/30.

    The engine has no owner concept (single-tenant per deployment), so this
    fans out over THIS request's own ``list_campaigns()`` -> ``GET
    /api/admin/history/{campaign_id}`` (the same read the admin-gated
    ``application_history`` route above already proxies) and collects every
    ``application_id`` that turns up — mirroring
    ``applicant_campaigns_routes._owner_campaign_ids`` /
    ``applicant_tracker_routes._owner_application_ids``'s "never trust a
    caller-supplied id" guard. A per-campaign read failure is skipped (logged,
    not fatal) so one inaccessible campaign never blanks the whole set.
    """
    try:
        campaigns = await engine.list_campaigns()
    except EngineError as exc:
        logger.debug("applicant admin owner-scope: campaigns read failed: %s", exc)
        return None
    if not isinstance(campaigns, list):
        return set()
    ids: set[str] = set()
    for campaign in campaigns:
        if not isinstance(campaign, dict):
            continue
        cid = campaign.get("id")
        if not cid:
            continue
        try:
            history = await engine.admin_application_history(str(cid))
        except EngineError as exc:
            logger.debug(
                "applicant admin owner-scope: history read failed for %s: %s", cid, exc
            )
            continue
        rows = history.get("applications") if isinstance(history, dict) else None
        for row in rows or []:
            if isinstance(row, dict) and row.get("application_id"):
                ids.add(str(row["application_id"]))
    return ids


def setup_applicant_admin_routes() -> APIRouter:
    router = APIRouter(prefix="/api/applicant/admin", tags=["applicant-admin"])

    # -- reachability -----------------------------------------------------

    @router.get("/status")
    async def status(request: Request) -> dict:
        """Lightweight reachability probe so the Activity panel can pick its state."""
        _require_admin(request)
        async with ApplicantEngineClient() as engine:
            available = await engine.engine_available()
        return {"engine_available": available}

    # -- tool registry (enable/disable the engine's tools) ----------------
    # The engine owns a real tool registry (GET /api/admin/tools, toggle via
    # POST /api/admin/tools/{key}?enabled=). The shared engine client is owned by
    # another lane, so — like the criteria proxy — we issue these through the
    # client's own request seam so every failure is still a typed EngineError.

    @router.get("/tools")
    async def list_tools(request: Request) -> dict:
        """List the engine's tools with their enabled state for the toggle panel.

        Soft-degrades: a down/unconfigured engine reports ``engine_available:
        false`` so the panel renders an offline note instead of erroring.
        """
        _require_admin(request)
        async with ApplicantEngineClient() as engine:
            return await _soft_get(
                engine._request("GET", "/api/admin/tools"),
                {"tools": []},
            )

    @router.post("/tools/{tool_key}")
    async def toggle_tool(tool_key: str, request: Request, body: ToggleToolIn) -> dict:
        """Enable or disable one engine tool (persisted + enforced at dispatch)."""
        _require_admin(request)
        async with ApplicantEngineClient() as engine:
            try:
                result = await engine._request(
                    "POST",
                    f"/api/admin/tools/{tool_key}",
                    params={"enabled": body.enabled},
                )
            except EngineError as exc:
                raise _engine_http_error(exc) from exc
        return result or {}

    # -- read-only debug/observability surface (all soft-degrade) ---------

    async def _soft_get(coro, empty: dict) -> dict:
        """Run a read coroutine, returning a soft empty payload if the engine is down.

        Read surfaces must never 5xx the Activity panel — an unreachable engine is
        an expected state it renders as an empty/offline view.
        """
        try:
            data = await coro
        except EngineError as exc:
            logger.debug("applicant admin read: engine unavailable: %s", exc)
            return {**empty, "engine_available": False}
        out = data if isinstance(data, dict) else {"items": data or []}
        out["engine_available"] = True
        return out

    @router.get("/history/{campaign_id}")
    async def application_history(campaign_id: str, request: Request, limit: int = 200) -> dict:
        """Per-application history for a campaign (status, role, variant, outcomes)."""
        _require_admin(request)
        async with ApplicantEngineClient() as engine:
            return await _soft_get(
                engine.admin_application_history(campaign_id, limit=limit),
                {"campaign_id": campaign_id, "applications": []},
            )

    @router.get("/outcomes/{application_id}")
    async def application_outcomes(application_id: str, request: Request) -> dict:
        """Outcome-event trail (submission / conversion) for one application."""
        _require_admin(request)
        async with ApplicantEngineClient() as engine:
            return await _soft_get(
                engine.admin_application_outcomes(application_id),
                {"application_id": application_id, "outcomes": []},
            )

    @router.get("/detections/{campaign_id}")
    async def application_detections(campaign_id: str, request: Request) -> dict:
        """Automation-detection signal history for a campaign."""
        _require_admin(request)
        async with ApplicantEngineClient() as engine:
            return await _soft_get(
                engine.admin_detections(campaign_id),
                {"campaign_id": campaign_id, "detections": []},
            )

    @router.get("/workflow/{application_id}")
    async def workflow_state(application_id: str, request: Request) -> dict:
        """Durable-workflow state (completed steps / pending recovery) for one app."""
        _require_admin(request)
        async with ApplicantEngineClient() as engine:
            return await _soft_get(
                engine.admin_workflow_state(application_id),
                {"application_id": application_id, "steps": []},
            )

    @router.get("/screenshots/{application_id}")
    async def application_screenshots(application_id: str, request: Request) -> dict:
        """Per-page screenshots captured during a run for one application."""
        _require_admin(request)
        async with ApplicantEngineClient() as engine:
            return await _soft_get(
                engine.admin_screenshots(application_id),
                {"application_id": application_id, "screenshots": []},
            )

    @router.get("/screenshots/{application_id}/{screenshot_id}/image")
    async def application_screenshot_image(
        application_id: str, screenshot_id: str, request: Request
    ):
        """Raw image bytes for one captured screenshot (dark-engine audit #28).

        Streams the real proof-of-work capture through so the Debug modal can
        render an actual thumbnail instead of just a filename label. 404s (via
        ``_engine_http_error``) when the engine has no bytes for this id.
        """
        _require_admin(request)
        async with ApplicantEngineClient() as engine:
            try:
                resp = await engine.admin_screenshot_image(application_id, screenshot_id)
            except EngineError as exc:
                raise _engine_http_error(exc) from exc
        from fastapi.responses import Response

        return Response(
            content=resp.content,
            media_type=resp.headers.get("content-type", "image/png"),
        )

    @router.get("/logs")
    async def logs(request: Request, limit: int = 100) -> dict:
        """Recent redacted run logs (the engine already secret-redacts entries)."""
        _require_admin(request)
        async with ApplicantEngineClient() as engine:
            return await _soft_get(engine.admin_logs(limit=limit), {"entries": []})

    @router.get("/variants/{campaign_id}")
    async def variant_library(campaign_id: str, request: Request) -> dict:
        """Resume-variant library: lineage / scores / approval state for a campaign."""
        _require_admin(request)
        async with ApplicantEngineClient() as engine:
            return await _soft_get(
                engine.admin_variants(campaign_id),
                {"campaign_id": campaign_id, "variants": []},
            )

    @router.get("/learning/{campaign_id}")
    async def learning_insights(campaign_id: str, request: Request) -> dict:
        """What the engine has learned for a campaign, in plain language.

        Conversion totals, the source funnel ranked by how well it converts, the
        roles that actually convert, and the exploration budget — read-only.
        Soft-degrades to an empty/offline payload when the engine is unreachable.
        """
        _require_admin(request)
        async with ApplicantEngineClient() as engine:
            return await _soft_get(
                engine.admin_learning(campaign_id),
                {
                    "campaign_id": campaign_id,
                    "summary": {},
                    "sources": [],
                    "converting_roles": [],
                },
            )

    @router.get("/stealth")
    async def stealth(request: Request) -> dict:
        """Honest best-effort stealth caveat + the live egress posture."""
        _require_admin(request)
        async with ApplicantEngineClient() as engine:
            return await _soft_get(engine.admin_stealth(), {})

    @router.get("/workspace-bridge")
    async def workspace_bridge(request: Request) -> dict:
        """Engine <-> workspace background-link health (dark-engine audit #71).

        Whether the callback channel (calendar sync / deep-research / the
        memory bridge) is configured and actually reachable — a bad/missing
        token silently disables all three with nothing telling the owner why.
        """
        _require_admin(request)
        async with ApplicantEngineClient() as engine:
            return await _soft_get(
                engine.admin_workspace_bridge(),
                {"configured": False, "reachable": False},
            )

    @router.get("/captcha-status")
    async def captcha_status(request: Request) -> dict:
        """Effective captcha strategy + real solve/avoid/handoff telemetry (dark-engine audit #67).

        Whether captcha handling is on the default human hand-off, or an
        avoidance/service strategy is actually wired and doing something —
        never fabricates a count the engine isn't genuinely tracking.
        """
        _require_admin(request)
        async with ApplicantEngineClient() as engine:
            return await _soft_get(
                engine.admin_captcha_status(),
                {"strategy": "human", "active": False},
            )

    @router.get("/capacity")
    async def capacity(request: Request) -> dict:
        """Sandbox concurrency snapshot: active vs. waiting applications (dark-engine audit #72)."""
        _require_admin(request)
        async with ApplicantEngineClient() as engine:
            return await _soft_get(
                engine.admin_capacity(),
                {"active": [], "waiting": [], "active_count": 0, "waiting_count": 0},
            )

    @router.get("/embedding-backend")
    async def embedding_backend(request: Request) -> dict:
        """Which embedding backend powers memory/dedup matching, plain-language (dark-engine audit #79)."""
        _require_admin(request)
        async with ApplicantEngineClient() as engine:
            return await _soft_get(
                engine.admin_embedding_backend(),
                {"backend": "unknown", "quality_tier": "unknown"},
            )

    @router.get("/prefill-diagnostics")
    async def prefill_diagnostics(request: Request) -> dict:
        """Recent pre-fill silent-degradation diagnostics (dark-engine audit #34).

        Credential/LLM/login failures that pre-fill degraded gracefully from
        (never crashed) but still left a trace for the operator instead of
        vanishing silently. Process-global, not campaign-scoped.
        """
        _require_admin(request)
        async with ApplicantEngineClient() as engine:
            return await _soft_get(engine.admin_prefill_diagnostics(), {"diagnostics": []})

    @router.get("/log/{application_id}")
    async def application_log(application_id: str, request: Request) -> dict:
        """Full logged detail for one application (detail + screenshots + outcomes)."""
        _require_admin(request)
        async with ApplicantEngineClient() as engine:
            return await _soft_get(
                engine.outcome_log(application_id),
                {"application_id": application_id},
            )

    @router.get("/snapshot/{application_id}")
    async def submission_snapshot(application_id: str, request: Request) -> dict:
        """The immutable submission snapshot recorded at the stop-boundary (#372).

        Surfaces the exact answers, material versions, posting, and timestamp that
        were submitted for this application — the durable record of what went out.
        Soft-degrades to an empty/offline body when no snapshot exists yet.
        """
        _require_admin(request)
        async with ApplicantEngineClient() as engine:
            return await _soft_get(
                engine.submission_snapshot(application_id),
                {"application_id": application_id, "has_snapshot": False},
            )

    # -- audit log export (downloadable JSON) -------------------------------

    @router.get("/audit-log/{campaign_id}/export.json")
    async def export_campaign_audit_log(campaign_id: str, request: Request):
        """Download the full action trail for a campaign as a JSON file."""
        _require_admin(request)
        async with ApplicantEngineClient() as engine:
            resp = await engine.audit_log_campaign_export(campaign_id)
        from fastapi.responses import Response

        return Response(
            content=resp.text if hasattr(resp, "text") else resp.content,
            media_type="application/json",
            headers={
                "Content-Disposition": f"attachment; filename=audit-log-{campaign_id}.json"
            },
        )

    @router.get("/audit-log/application/{application_id}/export.json")
    async def export_application_audit_log(application_id: str, request: Request):
        """Download the full action trail for one application as a JSON file."""
        _require_admin(request)
        async with ApplicantEngineClient() as engine:
            resp = await engine.audit_log_application_export(application_id)
        from fastapi.responses import Response

        return Response(
            content=resp.text if hasattr(resp, "text") else resp.content,
            media_type="application/json",
            headers={
                "Content-Disposition": f"attachment; filename=audit-log-{application_id}.json"
            },
        )

    # -- owner-reachable lane (no admin account required) -------------------
    # Dark-engine audit B4 items 29/30/32: the reads above are real
    # engine data belonging entirely to the owner of this single-tenant
    # deployment, but were reachable only from an admin account. These give
    # the owner their OWN data back, id-validated against THIS request's own
    # campaign/application fan-out (never a caller-supplied id trusted on its
    # own) instead of an admin gate.

    @router.get("/applications/{application_id}/workflow-status")
    async def owner_workflow_status(application_id: str, request: Request) -> dict:
        """Where one of the owner's OWN applications sits in the durable
        pipeline -- which steps completed and whether it's pending recovery
        (dark-engine audit item 29). Same engine read as the admin-gated
        ``/workflow/{id}`` above, reachable here without an admin account.
        """
        require_user(request)
        async with ApplicantEngineClient() as engine:
            owned = await _owner_application_ids(engine)
            if owned is None:
                raise HTTPException(status_code=503, detail="The engine is unavailable.")
            if application_id not in owned:
                raise HTTPException(status_code=404, detail="No such application.")
            return await _soft_get(
                engine.admin_workflow_state(application_id),
                {"application_id": application_id, "steps": []},
            )

    @router.get("/applications/{application_id}/audit-export.json")
    async def owner_export_application_audit_log(application_id: str, request: Request):
        """Download the full, ordered action trail for one of the owner's OWN
        applications as a JSON file (dark-engine audit item 30) -- the
        honesty artifact for a dispute or a bug report, previously reachable
        only via an admin account (``/audit-log/application/{id}/export.json``
        above).
        """
        require_user(request)
        async with ApplicantEngineClient() as engine:
            owned = await _owner_application_ids(engine)
            if owned is None:
                raise HTTPException(status_code=503, detail="The engine is unavailable.")
            if application_id not in owned:
                raise HTTPException(status_code=404, detail="No such application.")
            try:
                resp = await engine.audit_log_application_export(application_id)
            except EngineError as exc:
                raise _engine_http_error(exc) from exc
        from fastapi.responses import Response

        return Response(
            content=resp.text if hasattr(resp, "text") else resp.content,
            media_type="application/json",
            headers={
                "Content-Disposition": f"attachment; filename=audit-log-{application_id}.json"
            },
        )

    @router.get("/logs/mine")
    async def owner_recent_logs(request: Request, limit: int = 100) -> dict:
        """Recent redacted run logs, reachable without an admin account
        (dark-engine audit item 32). Process-global -- the engine has no
        per-application log index, so there is no id to deep-link a specific
        failure to yet; this only removes the admin-account requirement from
        the SAME read ``/logs`` above already proxies. A "view logs around
        this failure" deep link is deferred: every natural attachment point
        (a failed Portal item, a Tracker row, the Debug modal) is a file this
        change is explicitly scoped to leave untouched.
        """
        require_user(request)
        async with ApplicantEngineClient() as engine:
            return await _soft_get(engine.admin_logs(limit=limit), {"entries": []})

    # -- close the loop: mark submitted / re-detect (writes) --------------

    @router.post("/applications/{application_id}/mark-submitted")
    async def mark_submitted(
        application_id: str, request: Request, body: MarkSubmittedIn | None = None
    ) -> dict:
        """Record that a user manually completed/submitted this application.

        This closes the conversion-learning loop for manual / hand-off
        submissions the engine never auto-submitted, so they still teach the
        system which attributes converted.
        """
        _require_admin(request)
        payload = {"attributes_used": body.attributes_used} if body else {}
        async with ApplicantEngineClient() as engine:
            try:
                result = await engine.outcome_mark_submitted(application_id, payload)
            except EngineError as exc:
                raise _engine_http_error(exc) from exc
        return result or {}

    @router.post("/applications/{application_id}/detect")
    async def detect_submission(application_id: str, request: Request) -> dict:
        """Ask the engine to auto-detect a final submission in the live session."""
        _require_admin(request)
        async with ApplicantEngineClient() as engine:
            try:
                result = await engine.outcome_detect(application_id)
            except EngineError as exc:
                raise _engine_http_error(exc) from exc
        return result or {}

    # -- data-retention sweep, on demand (dark-engine audit #37) ----------
    # DESTRUCTIVE: permanently deletes personal data older than the retention
    # window. The engine derives its own default window from the currently
    # persisted Settings > Automation preference, so this is a plain "run it
    # now" trigger, not a second place to configure the window.

    @router.post("/retention/prune")
    async def run_retention_sweep(request: Request) -> dict:
        """Run the PII-retention sweep now and return the real per-store result.

        Admin-gated: this permanently deletes personal data (parsed PII / EEO
        answers / onboarding intakes) older than the retention window, the same
        cascade the dormant scheduler tick would eventually run on its own.
        """
        _require_admin(request)
        async with ApplicantEngineClient() as engine:
            try:
                result = await engine.admin_run_retention_sweep()
            except EngineError as exc:
                raise _engine_http_error(exc) from exc
        return result or {}

    return router
