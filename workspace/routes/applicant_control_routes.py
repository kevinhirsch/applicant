# routes/applicant_control_routes.py
"""Global pause / kill-switch ↔ engine bridge (trust-control lane).

The front-door's always-visible status strip needs a single, one-tap way to
**stop all automated work at once** — a global pause / resume the owner can reach
without hunting through an admin-only debug panel. The engine only exposes pause
and resume *per campaign*, so this proxy resolves the owner's campaigns (the same
owner-scoped ``list_campaigns()`` the activity feed fans out over) and fans the
pause/resume across every one of them.

This is a thin, auth-protected, owner-scoped proxy over
:class:`src.applicant_engine.ApplicantEngineClient`. The browser never reaches the
engine directly. It reuses the engine's existing per-campaign pause/resume gates
(``agent_run_pause`` / ``agent_run_resume``) rather than re-implementing them, and
never weakens a gate: it only calls the same engine endpoints the ops lane does.

Scoping mirrors the activity feed (``require_user``): the kill-switch is the
owner's own control over the owner's own campaigns, so any authenticated owner can
reach it from the strip — pausing is always the safe direction.

Endpoints (all under one prefix, ``/api/applicant/control``):

* ``POST /api/applicant/control/pause-all``  — pause every campaign the owner has.
* ``POST /api/applicant/control/resume-all`` — resume every campaign the owner has.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request

from src.applicant_engine import ApplicantEngineClient, EngineError, soft_degrade
from src.auth_helpers import require_user

logger = logging.getLogger(__name__)


# --- helpers ----------------------------------------------------------------


def _require_user(request: Request) -> str:
    """Require an authenticated owner (the global gate also enforces this)."""
    return require_user(request)


async def _owner_campaign_ids(engine: ApplicantEngineClient) -> "list[str] | dict":
    """Resolve the owner's campaign ids, or a soft-degrade payload on failure.

    The engine returns campaigns owner-scoped already (the same call the activity
    feed fans out over). On success this returns a ``list`` of id strings (possibly
    empty — "online, no campaign yet"). On an :class:`EngineError` it returns the
    :func:`soft_degrade` ``dict`` so a setup gate (409/403) reads as GATED and a
    transport failure reads as offline — callers detect it with ``isinstance(...,
    list)``.
    """
    try:
        campaigns = await engine.list_campaigns()
    except EngineError as exc:
        logger.debug("control: campaigns read failed (status=%s): %s", exc.status, exc)
        return soft_degrade(exc, {"paused": None})
    ids: list[str] = []
    if isinstance(campaigns, list):
        for campaign in campaigns:
            if isinstance(campaign, dict) and campaign.get("id"):
                ids.append(str(campaign["id"]))
    return ids


async def _fan_out(engine: ApplicantEngineClient, ids: list[str], action: str) -> tuple[list[str], list[str]]:
    """Call the per-campaign pause/resume over each id; collect ok/failed ids.

    A single campaign's failure must not abort the sweep — the kill-switch pauses
    as many as it can and reports which ones it couldn't reach.
    """
    method = engine.agent_run_pause if action == "pause" else engine.agent_run_resume
    ok: list[str] = []
    failed: list[str] = []
    for cid in ids:
        try:
            await method(cid)
            ok.append(cid)
        except EngineError as exc:
            logger.debug("control: %s failed for %s (status=%s): %s", action, cid, exc.status, exc)
            failed.append(cid)
    return ok, failed


def setup_applicant_control_routes() -> APIRouter:
    router = APIRouter(prefix="/api/applicant/control", tags=["applicant-control"])

    @router.post("/pause-all")
    async def pause_all(request: Request) -> dict:
        """Pause every campaign the owner has (the global kill-switch).

        Degrades soft on the campaign read: a setup gate returns ``gated: true``;
        a transport failure returns ``engine_available: false``. No campaign yet is
        a no-op success (nothing to pause). Individual per-campaign failures are
        collected in ``failed`` without aborting the sweep.
        """
        _require_user(request)
        async with ApplicantEngineClient() as engine:
            ids = await _owner_campaign_ids(engine)
            if not isinstance(ids, list):
                return {**ids, "paused": None}
            if not ids:
                return {"engine_available": True, "paused": True, "campaigns": 0, "failed": []}
            ok, failed = await _fan_out(engine, ids, "pause")
        return {
            "engine_available": True,
            "paused": len(failed) == 0,
            "campaigns": len(ok),
            "failed": failed,
        }

    @router.post("/resume-all")
    async def resume_all(request: Request) -> dict:
        """Resume every campaign the owner has (the inverse of the kill-switch)."""
        _require_user(request)
        async with ApplicantEngineClient() as engine:
            ids = await _owner_campaign_ids(engine)
            if not isinstance(ids, list):
                return {**ids, "paused": None}
            if not ids:
                return {"engine_available": True, "paused": False, "campaigns": 0, "failed": []}
            ok, failed = await _fan_out(engine, ids, "resume")
        return {
            "engine_available": True,
            # Still paused only if some campaigns could not be resumed.
            "paused": len(failed) > 0,
            "campaigns": len(ok),
            "failed": failed,
        }

    return router
