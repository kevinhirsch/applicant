# routes/applicant_activity_routes.py
"""Agent-activity feed ↔ engine bridge (surfacing-only).

The engine already produces a human-readable, plain-language account of what the
job agent is doing: a live status payload (running / paused, today's count, the
latest *intent* sentence) and a chronological history of recent runs, each with a
"verb-noun" intent sentence and a small stats block. This proxy SURFACES that
feed in the front-door — it adds no engine logic and creates no new engine state.

It backs two front-door surfaces:

* an always-visible **status strip** in the app chrome
  ("Applicant is: Scanning sources for new roles" / "Paused"), polling
  ``GET /api/applicant/activity/status``; and
* a dedicated **Activity page** in the left nav, rendering the chronological run
  history from ``GET /api/applicant/activity/runs``.

This is a thin, auth-protected, owner-scoped proxy over
:class:`src.applicant_engine.ApplicantEngineClient`. The browser never reaches the
engine directly, and every engine failure is normalised to a clean, well-formed
HTTP response so both surfaces degrade gracefully (the strip hides, the page shows
its empty/offline state) instead of throwing.

Scoping mirrors the Pending-Actions Portal: the activity feed is NOT gated behind
one active campaign. The engine exposes status/intent/runs per campaign, so this
proxy resolves the owner's campaign(s) (fanning out over ``list_campaigns()``) and
returns the first/most-relevant one's feed. Both reads degrade *soft*: an
unreachable engine (or no campaign yet) returns ``engine_available``/``has_activity``
flags with an empty, well-formed body rather than a 5xx.

Endpoints (all under one prefix, ``/api/applicant/activity``):

* ``GET /api/applicant/activity/status`` — live status for the strip
  (running/paused, intent, today's count, scheduler ticks).
* ``GET /api/applicant/activity/intent`` — just the latest intent sentence.
* ``GET /api/applicant/activity/runs``   — the chronological run history.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Request

from src.applicant_engine import ApplicantEngineClient, EngineError
from src.auth_helpers import require_user

logger = logging.getLogger(__name__)


# --- helpers ----------------------------------------------------------------


def _require_user(request: Request) -> str:
    """Require an authenticated owner (the global gate also enforces this)."""
    return require_user(request)


def _campaign_label(campaign: dict) -> str:
    """Best human label for a campaign dict from the engine."""
    return str(campaign.get("name") or campaign.get("id") or "")


async def _owner_campaigns(engine: ApplicantEngineClient) -> Optional[list[dict]]:
    """Resolve the owner's campaigns, or ``None`` when the engine is unreachable.

    The engine returns campaigns owner-scoped already (the same call the Portal
    fans out over). ``None`` means "offline" so callers can return the soft
    ``engine_available: false`` payload; an empty list means "online, no campaign
    yet" so callers can return the soft ``has_activity: false`` payload.
    """
    try:
        campaigns = await engine.list_campaigns()
    except EngineError as exc:
        logger.debug("activity: engine unavailable listing campaigns: %s", exc)
        return None
    return [c for c in campaigns if isinstance(c, dict)] if isinstance(campaigns, list) else []


def _first_campaign(campaigns: list[dict]) -> Optional[tuple[str, str]]:
    """The first campaign's ``(id, label)`` if any, else ``None``."""
    for campaign in campaigns:
        cid = campaign.get("id")
        if cid:
            return str(cid), _campaign_label(campaign)
    return None


def setup_applicant_activity_routes() -> APIRouter:
    router = APIRouter(prefix="/api/applicant/activity", tags=["applicant-activity"])

    # -- live status (status strip) ---------------------------------------

    @router.get("/status")
    async def activity_status(request: Request) -> dict:
        """Live agent status for the always-visible status strip.

        Resolves the owner's first campaign and proxies the engine's status
        payload (``active``, ``run_mode``, ``applied_today``, ``latest_intent``,
        ``scheduler`` ticks, …). Degrades soft: an unreachable engine returns
        ``engine_available: false``; no campaign yet returns ``has_activity:
        false`` — both keep the body well-formed so the strip just hides.
        """
        _require_user(request)
        async with ApplicantEngineClient() as engine:
            campaigns = await _owner_campaigns(engine)
            if campaigns is None:
                return {"engine_available": False, "has_activity": False}
            first = _first_campaign(campaigns)
            if first is None:
                return {"engine_available": True, "has_activity": False}
            cid, cname = first
            try:
                data = await engine.agent_run_status(cid)
            except EngineError as exc:
                logger.debug("activity: status fetch failed for %s: %s", cid, exc)
                return {"engine_available": True, "has_activity": False}
        out = data if isinstance(data, dict) else {}
        out.setdefault("campaign_id", cid)
        out["campaign_name"] = cname
        out["engine_available"] = True
        out["has_activity"] = True
        return out

    # -- latest intent sentence -------------------------------------------

    @router.get("/intent")
    async def activity_intent(request: Request) -> dict:
        """The latest plain-language "verb-noun" intent sentence for the strip.

        A lighter read than ``/status`` for surfaces that only want the sentence.
        Degrades soft the same way.
        """
        _require_user(request)
        async with ApplicantEngineClient() as engine:
            campaigns = await _owner_campaigns(engine)
            if campaigns is None:
                return {"engine_available": False, "has_activity": False, "intent": None}
            first = _first_campaign(campaigns)
            if first is None:
                return {"engine_available": True, "has_activity": False, "intent": None}
            cid, cname = first
            try:
                data = await engine.agent_run_intent(cid)
            except EngineError as exc:
                logger.debug("activity: intent fetch failed for %s: %s", cid, exc)
                return {"engine_available": True, "has_activity": False, "intent": None}
        out = data if isinstance(data, dict) else {"intent": data}
        out.setdefault("campaign_id", cid)
        out["campaign_name"] = cname
        out["engine_available"] = True
        out["has_activity"] = bool(out.get("intent"))
        return out

    # -- chronological run history (Activity page) ------------------------

    @router.get("/runs")
    async def activity_runs(request: Request) -> dict:
        """The chronological run history for the dedicated Activity page.

        Each item is the engine's own run record (``intent`` sentence, ``run_mode``,
        ``throughput_target``, and a ``stats`` block) — latest first. Degrades soft:
        an unreachable engine returns ``engine_available: false``; no campaign yet
        returns ``has_activity: false`` with an empty ``items`` list so the page
        renders its empty state.
        """
        _require_user(request)
        async with ApplicantEngineClient() as engine:
            campaigns = await _owner_campaigns(engine)
            if campaigns is None:
                return {"engine_available": False, "has_activity": False, "count": 0, "items": []}
            first = _first_campaign(campaigns)
            if first is None:
                return {"engine_available": True, "has_activity": False, "count": 0, "items": []}
            cid, cname = first
            try:
                data = await engine.agent_runs_list(cid)
            except EngineError as exc:
                logger.debug("activity: runs fetch failed for %s: %s", cid, exc)
                return {"engine_available": True, "has_activity": False, "count": 0, "items": []}
        items: list[Any] = []
        if isinstance(data, dict):
            items = data.get("items") or []
        elif isinstance(data, list):
            items = data
        items = [it for it in items if isinstance(it, dict)]
        return {
            "engine_available": True,
            "has_activity": bool(items),
            "campaign_id": cid,
            "campaign_name": cname,
            "count": len(items),
            "items": items,
        }

    # -- consolidated now / next / recent snapshot (Agent activity panel) --

    @router.get("/snapshot")
    async def activity_snapshot(request: Request) -> dict:
        """The engine's consolidated 'what the agent is doing' snapshot.

        Proxies the engine's single read-only ``now`` / ``next`` / ``recent``
        summary (first-person, plain-language) for the front-door agent-activity
        panel. Degrades soft exactly like the sibling reads: an unreachable engine
        returns ``engine_available: false``; no campaign yet (or a status fetch
        error) returns ``has_activity: false`` with an empty, well-formed body so
        the panel renders its offline/empty state instead of throwing.
        """
        _require_user(request)
        async with ApplicantEngineClient() as engine:
            campaigns = await _owner_campaigns(engine)
            if campaigns is None:
                return {"engine_available": False, "has_activity": False}
            first = _first_campaign(campaigns)
            if first is None:
                return {"engine_available": True, "has_activity": False}
            cid, cname = first
            try:
                data = await engine.agent_status(cid)
            except EngineError as exc:
                logger.debug("activity: snapshot fetch failed for %s: %s", cid, exc)
                return {"engine_available": True, "has_activity": False}
        out = data if isinstance(data, dict) else {}
        out.setdefault("campaign_id", cid)
        out["campaign_name"] = cname
        out["engine_available"] = True
        out["has_activity"] = True
        return out

    return router
