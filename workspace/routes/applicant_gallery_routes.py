# routes/applicant_gallery_routes.py
"""Gallery ↔ engine bridge (surfacing-only, issue #296).

The engine already captures, per campaign, the per-page **screenshots** archived
during pre-fill and the **generated materials** drafted for each role. This proxy
SURFACES that as browsable gallery collections in the front-door — it adds no
engine logic and creates no new engine state. It is the Applicant materials
gallery and is wholly separate from the workspace's own native image gallery
(``/api/gallery`` lives under ``/gallery``; this lives under ``/api/applicant/gallery``).

It is a thin, auth-protected, owner-scoped proxy over
:class:`src.applicant_engine.ApplicantEngineClient`. The browser never reaches the
engine directly, and every engine failure is normalised to a clean, well-formed
HTTP response so the surface degrades gracefully (empty/offline state) instead of
throwing.

Scoping mirrors the Activity feed and the Pending-Actions Portal: the gallery is
NOT gated behind one active campaign. The engine exposes collections per campaign,
so this proxy resolves the owner's campaign(s) and returns the first/most-relevant
one's gallery. It also accepts an explicit ``campaign_id`` so a campaign chooser
can target a specific job search. Both reads degrade *soft*: an unreachable engine
(or no campaign yet) returns ``engine_available`` / ``has_gallery`` flags with an
empty, well-formed body rather than a 5xx.

Endpoints (all under one prefix, ``/api/applicant/gallery``):

* ``GET /api/applicant/gallery/campaigns`` — campaigns to pick a gallery for.
* ``GET /api/applicant/gallery``            — the first campaign's collections.
* ``GET /api/applicant/gallery/{campaign_id}`` — a specific campaign's collections.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Request

from src.applicant_engine import ApplicantEngineClient, EngineError, soft_degrade
from src.auth_helpers import require_user

logger = logging.getLogger(__name__)


# --- helpers ----------------------------------------------------------------


def _campaign_label(campaign: dict) -> str:
    """Best human label for a campaign dict from the engine."""
    return str(campaign.get("name") or campaign.get("id") or "")


async def _owner_campaigns(engine: ApplicantEngineClient) -> "list[dict] | dict":
    """Resolve the owner's campaigns, or a soft-degrade payload on failure.

    On success this returns a ``list`` (possibly empty — "online, no campaign yet").

    On an :class:`EngineError` it returns a ``dict`` built by :func:`soft_degrade`,
    which distinguishes a client-correctable GATE (``gated: true`` + the engine's
    message, ``engine_available: true``) from a genuine TRANSPORT-OFFLINE
    (``engine_available: false``) — so a 409 setup gate no longer dishonestly reads
    as "engine offline" here, matching the activity/ops/portal proxies. Callers
    detect the failure with ``isinstance(result, list)`` and merge the dict with
    their own well-formed empty body (``has_gallery``/``campaigns``/collections).
    """
    try:
        campaigns = await engine.list_campaigns()
    except EngineError as exc:
        logger.debug("gallery: campaigns read failed (status=%s): %s", exc.status, exc)
        return soft_degrade(exc, {})
    return [c for c in campaigns if isinstance(c, dict)] if isinstance(campaigns, list) else []


def _first_campaign(campaigns: list[dict]) -> Optional[tuple[str, str]]:
    """The first campaign's ``(id, label)`` if any, else ``None``."""
    for campaign in campaigns:
        cid = campaign.get("id")
        if cid:
            return str(cid), _campaign_label(campaign)
    return None


def _empty_gallery() -> dict:
    """A well-formed empty collections body the front end can render."""
    return {
        "screenshots": {"count": 0, "items": []},
        "materials": {"count": 0, "items": []},
    }


def setup_applicant_gallery_routes() -> APIRouter:
    router = APIRouter(prefix="/api/applicant/gallery", tags=["applicant-gallery"])

    @router.get("/campaigns")
    async def list_campaigns(request: Request) -> dict:
        """Campaigns the gallery view can pick a collection for (read-only)."""
        require_user(request)
        async with ApplicantEngineClient() as engine:
            campaigns = await _owner_campaigns(engine)
        if not isinstance(campaigns, list):
            return {**campaigns, "campaigns": []}
        return {"engine_available": True, "campaigns": campaigns}

    @router.get("")
    async def gallery_default(request: Request) -> dict:
        """Gallery collections for the owner's first campaign.

        Degrades soft: an unreachable engine returns ``engine_available: false``;
        no campaign yet returns ``has_gallery: false`` with an empty, well-formed
        body so the grid renders its empty/offline state.
        """
        require_user(request)
        async with ApplicantEngineClient() as engine:
            campaigns = await _owner_campaigns(engine)
            if not isinstance(campaigns, list):
                return {**campaigns, "has_gallery": False, **_empty_gallery()}
            first = _first_campaign(campaigns)
            if first is None:
                return {"engine_available": True, "has_gallery": False, **_empty_gallery()}
            cid, cname = first
            try:
                data = await engine.gallery(cid)
            except EngineError as exc:
                logger.debug("gallery: fetch failed for %s: %s", cid, exc)
                return {"engine_available": True, "has_gallery": False, **_empty_gallery()}
        return _shape(data, cid, cname)

    @router.get("/{campaign_id}")
    async def gallery_for_campaign(request: Request, campaign_id: str) -> dict:
        """Gallery collections for a SPECIFIC campaign (owner-scoped chooser target).

        Scoping: the engine resolves campaigns owner-scoped, so we verify the
        requested ``campaign_id`` belongs to the owner before proxying — a caller
        cannot read another owner's gallery. Degrades soft like the default read.
        """
        require_user(request)
        async with ApplicantEngineClient() as engine:
            campaigns = await _owner_campaigns(engine)
            if not isinstance(campaigns, list):
                return {**campaigns, "has_gallery": False, **_empty_gallery()}
            owned = {str(c.get("id")): _campaign_label(c) for c in campaigns if c.get("id")}
            if campaign_id not in owned:
                # Not the owner's campaign (or no campaign yet): empty, well-formed.
                return {"engine_available": True, "has_gallery": False, **_empty_gallery()}
            try:
                data = await engine.gallery(campaign_id)
            except EngineError as exc:
                logger.debug("gallery: fetch failed for %s: %s", campaign_id, exc)
                return {"engine_available": True, "has_gallery": False, **_empty_gallery()}
        return _shape(data, campaign_id, owned[campaign_id])

    return router


def _shape(data: object, cid: str, cname: str) -> dict:
    """Normalise the engine gallery payload into the front-door body shape."""
    out = data if isinstance(data, dict) else {}
    screenshots = out.get("screenshots") if isinstance(out.get("screenshots"), dict) else {"count": 0, "items": []}
    materials = out.get("materials") if isinstance(out.get("materials"), dict) else {"count": 0, "items": []}
    has = bool(screenshots.get("count") or materials.get("count"))
    return {
        "engine_available": True,
        "has_gallery": has,
        "campaign_id": cid,
        "campaign_name": cname,
        "screenshots": screenshots,
        "materials": materials,
    }
