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

Scoping: these are owner/admin surfaces — application history and raw logs are
operator-grade detail, so they require an admin account (and an authenticated
session in every mode). In single-user / unconfigured mode there is no admin
distinction, so the lone owner sees them (matching the rest of the workspace).

This file is ADDITIVE and disjoint from the other ``applicant_*`` proxies: it
mounts its own ``/api/applicant/admin`` prefix and leaves them untouched. It does
NOT edit the shared engine client beyond the append-only methods that lane added
(``admin_*`` / ``outcome_*``).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from src.applicant_engine import ApplicantEngineClient, EngineError
from src.auth_helpers import get_current_user

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
        # Single-user / first-run: no admin distinction; allow the lone owner.
        return owner or ""

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

    @router.get("/log/{application_id}")
    async def application_log(application_id: str, request: Request) -> dict:
        """Full logged detail for one application (detail + screenshots + outcomes)."""
        _require_admin(request)
        async with ApplicantEngineClient() as engine:
            return await _soft_get(
                engine.outcome_log(application_id),
                {"application_id": application_id},
            )

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

    return router
