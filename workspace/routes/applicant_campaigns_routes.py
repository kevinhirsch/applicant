# routes/applicant_campaigns_routes.py
"""Campaign + discovery-source settings ↔ engine bridge (issue #301).

Surfaces the engine's campaign config (run mode, daily throughput target,
exploration budget, archive/reactivate, rename) and the per-campaign discovery
source toggles in the white-labeled Settings surface. The engine owns ALL the
logic and the safety clamps (throughput hard cap, budget range); this is a thin,
auth-protected, owner-scoped proxy over
:class:`src.applicant_engine.ApplicantEngineClient`.

Owner-scoping: every mutating call FIRST resolves the owner's campaigns from the
engine and rejects any ``campaign_id`` the owner does not have — a caller cannot
edit another owner's campaign (mirrors the Gallery proxy, #296). Reads degrade
soft: an unreachable engine returns ``engine_available: false`` with an empty,
well-formed body instead of a 5xx so the panel shows its offline state.

Cross-account isolation (DISC-15): the engine itself is single-tenant (no owner
concept), so the read/list endpoints below (``GET`` list, ``GET .../sources``,
``GET .../audit-log/export.json``) are gated by
``src.auth_helpers.require_engine_owner`` rather than the plain auth-only
``require_user`` — otherwise ANY authenticated workspace account (not just the
real owner) could read the one deployment owner's campaign config, discovery
sources, and audit trail. Mirrors the fix already applied to the notification
inbox and pending-actions feed in ``applicant_portal_routes.py``.

Cross-account isolation, write endpoints (DISC-15b): the "id validated against
the owner's own campaign list" check on ``PATCH``/``clone``/``DELETE``/
``sources/{key}`` below is only IDOR protection against foreign ids -- since
the engine is single-tenant, that check was trivially satisfied for ANY
authenticated account (the fan-out itself has no owner concept to filter on),
so a second workspace account could still resolve and mutate the real owner's
campaigns. All four write endpoints are now additionally gated by the same
``require_engine_owner`` the reads use above.

Endpoints (all under ``/api/applicant/campaigns``):

* ``GET  /api/applicant/campaigns``                       — campaigns + config.
* ``PATCH /api/applicant/campaigns/{campaign_id}``        — rename/archive/re-tune.
* ``POST /api/applicant/campaigns/{campaign_id}/clone``   — duplicate under a new
  identity (dark-engine audit item 36) — "same search, new city".
* ``DELETE /api/applicant/campaigns/{campaign_id}``       — permanently delete + purge (#363).
* ``GET  /api/applicant/campaigns/{campaign_id}/guardrails`` — cost & pace
  guardrails (P1-6): today's applications vs. the daily target/hard cap, an
  estimated spend, and a monthly projection. The engine enforces the caps and
  computes every dollar figure server-side; this is a read-only proxy.
* ``GET  /api/applicant/campaigns/{campaign_id}/sources`` — discovery sources.
* ``PUT  /api/applicant/campaigns/{campaign_id}/sources/{source_key}`` — toggle.
* ``GET  /api/applicant/campaigns/{campaign_id}/audit-log/export.json`` —
  download the ordered action trail for the campaign (dark-engine audit item
  31): the engine already builds this export (``routers/audit.py``), but it
  was reachable only from an admin account (``applicant_admin_routes.py``);
  this owner-scoped lane reuses the exact same engine export, just gated by
  campaign ownership instead of an admin flag — the honesty artifact the
  single owner of this deployment needs when deciding whether to trust the
  agent shouldn't require operator rank for their own data.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from src.applicant_engine import ApplicantEngineClient, EngineError
from src.auth_helpers import require_engine_owner

logger = logging.getLogger(__name__)


class UpdateCampaignIn(BaseModel):
    """Partial campaign-config update — every field optional (engine clamps ranges)."""

    name: Optional[str] = None
    run_mode: Optional[str] = None
    throughput_target: Optional[int] = None
    exploration_budget: Optional[float] = None
    active: Optional[bool] = None


class CloneCampaignIn(BaseModel):
    """Optional new name for the duplicate — the engine names it from the source
    campaign when omitted."""

    name: Optional[str] = None


class ToggleSourceIn(BaseModel):
    enabled: bool


async def _owner_campaign_ids(engine: ApplicantEngineClient) -> Optional[set[str]]:
    """The owner's campaign ids, or ``None`` when the engine is unreachable."""
    try:
        campaigns = await engine.list_campaigns()
    except EngineError as exc:
        logger.debug("campaigns: engine unavailable: %s", exc)
        return None
    if not isinstance(campaigns, list):
        return set()
    return {str(c.get("id")) for c in campaigns if isinstance(c, dict) and c.get("id")}


def setup_applicant_campaigns_routes() -> APIRouter:
    router = APIRouter(prefix="/api/applicant/campaigns", tags=["applicant-campaigns"])

    @router.get("")
    async def list_campaigns(request: Request) -> dict:
        """The owner's campaigns with full config (read-only, soft-degrades).

        Owner-scoped (DISC-15): the engine has no owner concept of its own, so
        this is gated by ``require_engine_owner`` rather than plain
        ``require_user`` -- otherwise any other authenticated workspace
        account could list the real owner's campaign config.
        """
        require_engine_owner(request)
        async with ApplicantEngineClient() as engine:
            try:
                campaigns = await engine.list_campaigns()
            except EngineError as exc:
                logger.debug("campaigns: list failed: %s", exc)
                return {"engine_available": False, "campaigns": []}
        items = [c for c in campaigns if isinstance(c, dict)] if isinstance(campaigns, list) else []
        return {"engine_available": True, "campaigns": items}

    @router.patch("/{campaign_id}")
    async def update_campaign(
        request: Request, campaign_id: str, body: UpdateCampaignIn
    ) -> dict:
        """Rename / archive / re-tune a campaign (owner-scoped).

        Owner-scoped (DISC-15b): gated by ``require_engine_owner`` rather than
        plain ``require_user`` -- see the module docstring's "write endpoints"
        note above for why the id-ownership check alone was not enough.
        """
        require_engine_owner(request)
        async with ApplicantEngineClient() as engine:
            owned = await _owner_campaign_ids(engine)
            if owned is None:
                raise HTTPException(status_code=503, detail="The engine is unavailable.")
            if campaign_id not in owned:
                raise HTTPException(status_code=404, detail="No such campaign.")
            payload = body.model_dump(exclude_none=True)
            try:
                updated = await engine.update_campaign(campaign_id, payload)
            except EngineError as exc:
                logger.debug("campaigns: update failed for %s: %s", campaign_id, exc)
                raise HTTPException(
                    status_code=exc.status or 502, detail=str(exc)
                ) from exc
        return updated if isinstance(updated, dict) else {}

    @router.post("/{campaign_id}/clone", status_code=201)
    async def clone_campaign(
        request: Request, campaign_id: str, body: CloneCampaignIn
    ) -> dict:
        """Duplicate a campaign's criteria/settings under a new identity
        (owner-scoped, dark-engine audit item 36) -- the natural "same search,
        new city" move: start a fresh campaign from an existing one's config
        instead of rebuilding it by hand. A caller can only clone a campaign
        they own; the reserved system campaign is never in the owner's list so
        it can never be a clone source here either.

        Owner-scoped (DISC-15b): gated by ``require_engine_owner`` (see
        ``update_campaign`` above).
        """
        require_engine_owner(request)
        async with ApplicantEngineClient() as engine:
            owned = await _owner_campaign_ids(engine)
            if owned is None:
                raise HTTPException(status_code=503, detail="The engine is unavailable.")
            if campaign_id not in owned:
                raise HTTPException(status_code=404, detail="No such campaign.")
            try:
                cloned = await engine.clone_campaign(campaign_id, body.name)
            except EngineError as exc:
                logger.debug("campaigns: clone failed for %s: %s", campaign_id, exc)
                raise HTTPException(
                    status_code=exc.status or 502, detail=str(exc)
                ) from exc
        return cloned if isinstance(cloned, dict) else {}

    @router.delete("/{campaign_id}")
    async def delete_campaign(request: Request, campaign_id: str) -> dict:
        """Permanently delete a campaign and purge its data (owner-scoped, #363).

        Irreversible — the engine cascades the purge across every store (résumés,
        parsed PII, generated materials, application history, banked credentials).
        A caller can only delete a campaign they own; the reserved system campaign
        is never in the owner's list so it can never be targeted here either.

        Owner-scoped (DISC-15b): gated by ``require_engine_owner`` (see
        ``update_campaign`` above).
        """
        require_engine_owner(request)
        async with ApplicantEngineClient() as engine:
            owned = await _owner_campaign_ids(engine)
            if owned is None:
                raise HTTPException(status_code=503, detail="The engine is unavailable.")
            if campaign_id not in owned:
                raise HTTPException(status_code=404, detail="No such campaign.")
            try:
                result = await engine.delete_campaign(campaign_id)
            except EngineError as exc:
                logger.debug("campaigns: delete failed for %s: %s", campaign_id, exc)
                raise HTTPException(
                    status_code=exc.status or 502, detail=str(exc)
                ) from exc
        return result if isinstance(result, dict) else {"deleted": True}

    @router.get("/{campaign_id}/audit-log/export.json")
    async def export_campaign_audit_log(request: Request, campaign_id: str):
        """Download the full ordered action trail for one of the owner's OWN
        campaigns as a JSON file (dark-engine audit item 31) -- the same
        export the engine already builds (``GET
        /api/admin/audit-log/{campaign_id}/export.json``), previously
        reachable only from an admin account. Owner-scoped exactly like
        ``delete_campaign``/``clone_campaign`` above: a caller can only
        export a campaign they own.

        Owner-scoped (DISC-15): additionally gated by ``require_engine_owner``
        -- this is a raw audit-log download of the deployment owner's own
        action trail, so it must not be reachable by any other authenticated
        workspace account either.
        """
        require_engine_owner(request)
        async with ApplicantEngineClient() as engine:
            owned = await _owner_campaign_ids(engine)
            if owned is None:
                raise HTTPException(status_code=503, detail="The engine is unavailable.")
            if campaign_id not in owned:
                raise HTTPException(status_code=404, detail="No such campaign.")
            try:
                resp = await engine.audit_log_campaign_export(campaign_id)
            except EngineError as exc:
                logger.debug(
                    "campaigns: audit-log export failed for %s: %s", campaign_id, exc
                )
                raise HTTPException(
                    status_code=exc.status or 502, detail=str(exc)
                ) from exc
        from fastapi.responses import Response

        return Response(
            content=resp.text if hasattr(resp, "text") else resp.content,
            media_type="application/json",
            headers={
                "Content-Disposition": f"attachment; filename=audit-log-{campaign_id}.json"
            },
        )

    @router.get("/{campaign_id}/guardrails")
    async def get_guardrails(request: Request, campaign_id: str) -> dict:
        """Cost & pace guardrails (P1-6): today's pace/spend + a monthly projection.

        The engine enforces the daily target/hard cap and computes every dollar
        figure server-side (never caller-supplied); this proxy only surfaces it.
        Owner-scoped (DISC-15) and soft-degrading, exactly like ``list_sources``
        below.
        """
        require_engine_owner(request)
        async with ApplicantEngineClient() as engine:
            owned = await _owner_campaign_ids(engine)
            if owned is None:
                return {"engine_available": False, "campaign_id": campaign_id}
            if campaign_id not in owned:
                return {"engine_available": True, "campaign_id": campaign_id}
            try:
                data = await engine.get_campaign_guardrails(campaign_id)
            except EngineError as exc:
                logger.debug("campaigns: guardrails read failed for %s: %s", campaign_id, exc)
                return {"engine_available": True, "campaign_id": campaign_id}
        out = data if isinstance(data, dict) else {}
        return {"engine_available": True, "campaign_id": campaign_id, **out}

    @router.get("/{campaign_id}/sources")
    async def list_sources(request: Request, campaign_id: str) -> dict:
        """The campaign's discovery sources + per-source yield stats (owner-scoped).

        Owner-scoped (DISC-15): gated by ``require_engine_owner`` -- a read of
        the deployment owner's discovery-source config and yield stats, not
        just any authenticated workspace account's.
        """
        require_engine_owner(request)
        async with ApplicantEngineClient() as engine:
            owned = await _owner_campaign_ids(engine)
            if owned is None:
                return {"engine_available": False, "campaign_id": campaign_id, "items": []}
            if campaign_id not in owned:
                return {"engine_available": True, "campaign_id": campaign_id, "items": []}
            try:
                data = await engine.list_discovery_sources(campaign_id)
            except EngineError as exc:
                logger.debug("campaigns: sources read failed for %s: %s", campaign_id, exc)
                return {"engine_available": True, "campaign_id": campaign_id, "items": []}
        out = data if isinstance(data, dict) else {}
        items = out.get("items") if isinstance(out.get("items"), list) else []
        return {"engine_available": True, "campaign_id": campaign_id, "items": items}

    @router.put("/{campaign_id}/sources/{source_key}")
    async def toggle_source(
        request: Request, campaign_id: str, source_key: str, body: ToggleSourceIn
    ) -> dict:
        """Enable/disable a discovery source for a campaign (owner-scoped).

        Owner-scoped (DISC-15b): gated by ``require_engine_owner`` (see
        ``update_campaign`` above).
        """
        require_engine_owner(request)
        async with ApplicantEngineClient() as engine:
            owned = await _owner_campaign_ids(engine)
            if owned is None:
                raise HTTPException(status_code=503, detail="The engine is unavailable.")
            if campaign_id not in owned:
                raise HTTPException(status_code=404, detail="No such campaign.")
            try:
                result = await engine.toggle_discovery_source(
                    campaign_id, source_key, body.enabled
                )
            except EngineError as exc:
                logger.debug("campaigns: toggle failed for %s/%s: %s", campaign_id, source_key, exc)
                raise HTTPException(
                    status_code=exc.status or 502, detail=str(exc)
                ) from exc
        return result if isinstance(result, dict) else {}

    return router
