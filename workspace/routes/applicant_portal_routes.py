# routes/applicant_portal_routes.py
"""Pending-Actions Portal ↔ engine bridge (CRIT-portal).

The *Portal* is the workspace's primary home-base surface: a single, standalone
place that lists EVERYTHING awaiting the owner across ALL of their job-search
campaigns — agent questions, material reviews (cover letters / screening answers
/ resumes), missing details the engine needs to keep going, account-creation /
verification hand-offs that carry a live session, emergency data hand-offs, and
digest decisions. Each row is actionable.

This is a thin, auth-protected, owner-scoped proxy over
:class:`src.applicant_engine.ApplicantEngineClient`. The browser never reaches
the engine directly, and every engine failure is normalised to a clean HTTP
response so the portal degrades gracefully instead of throwing.

Why a dedicated proxy (vs. the chat bridge's per-campaign pending list): the
portal is NOT gated behind one active campaign. The engine exposes pending
actions per campaign (``GET /api/pending-actions/{campaign_id}``), so this proxy
fans out over the owner's campaigns and merges the results into one feed, tagging
each item with its originating campaign so the UI can group/label it. Resolving
and supplying-a-missing-detail are also proxied here so the whole portal speaks to
one prefix (``/api/applicant/portal``).

Endpoints:

* ``GET  /api/applicant/portal/pending``            — aggregated feed + total count.
* ``POST /api/applicant/portal/actions/{id}/resolve`` — mark one item handled.
* ``POST /api/applicant/portal/missing-attribute``    — supply a missing detail and
  resume the blocked application (engine ``acquire-missing``), then resolve the
  originating action if one was given.

Design notes:

* Auth: these routes are NOT in the auth-exempt list, so the global gate in
  ``app.py`` requires a logged-in session. We additionally call ``require_user``
  so a middleware misconfig can't open them up.
* Errors: a transport failure (engine down / timeout) → 503; an engine HTTP
  error is forwarded with its own status + detail (so e.g. a 409 confirm-gate
  passes through). No raw httpx escapes — the engine client guarantees a typed
  :class:`EngineError`.
* The aggregate GET degrades *soft*: an unreachable engine returns an empty,
  well-formed payload with ``engine_available: false`` rather than 5xx, so the
  portal renders its "connect the engine" empty state. A single campaign that
  errors does not sink the whole feed — it is skipped and noted.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from src.applicant_engine import ApplicantEngineClient, EngineError
from src.auth_helpers import require_user

logger = logging.getLogger(__name__)


# --- request bodies ---------------------------------------------------------


class MissingAttributeIn(BaseModel):
    """Supply a value for a detail the engine flagged as missing (FR-ATTR-5)."""

    name: str
    value: str
    campaign_id: Optional[str] = None
    action_id: Optional[str] = None
    confirm: bool = False


# --- helpers ----------------------------------------------------------------


def _require_user(request: Request) -> str:
    """Require an authenticated owner (the global gate also enforces this)."""
    return require_user(request)


def _engine_http_error(exc: EngineError) -> HTTPException:
    """Translate a typed :class:`EngineError` into an HTTPException for a *write*.

    A transport-level failure (no ``status``) means the engine is unreachable →
    503. An engine HTTP error is forwarded with its own status + the engine's own
    detail so the user sees the real reason (e.g. a 409 confirm gate).
    """
    if exc.status is None:
        return HTTPException(
            status_code=503,
            detail="The Applicant engine is unavailable right now. Please try again shortly.",
        )
    detail = exc.detail if exc.detail not in (None, "") else exc.message
    return HTTPException(status_code=exc.status, detail=detail)


def _campaign_label(campaign: dict) -> str:
    """Best human label for a campaign dict from the engine."""
    return str(campaign.get("name") or campaign.get("id") or "")


def _shape_item(raw: dict, *, campaign_id: str, campaign_name: str) -> dict:
    """Normalise one engine pending-action into the portal's row shape.

    Keeps the engine's own fields and adds the campaign context the portal needs
    to group/label rows (the engine returns items scoped to one campaign, so it
    doesn't echo the campaign back per item).
    """
    item = dict(raw or {})
    item.setdefault("campaign_id", campaign_id)
    item["campaign_name"] = campaign_name
    return item


async def _resolve_campaign(engine: ApplicantEngineClient, explicit: Optional[str]) -> str:
    """Resolve the campaign for a missing-attribute write.

    An explicit id wins; otherwise take the engine's first campaign. Raises 409
    if there is no campaign yet so the UI can prompt instead of writing to a
    missing campaign. A down engine during lookup surfaces through the same clean
    503 mapping as everything else.
    """
    if explicit:
        return explicit
    try:
        campaigns = await engine.list_campaigns()
    except EngineError as exc:
        raise _engine_http_error(exc) from exc
    if isinstance(campaigns, list) and campaigns:
        first = campaigns[0]
        cid = first.get("id") if isinstance(first, dict) else None
        if cid:
            return str(cid)
    raise HTTPException(409, "No job-search workspace exists yet. Finish onboarding first.")


def setup_applicant_portal_routes() -> APIRouter:
    router = APIRouter(prefix="/api/applicant/portal", tags=["applicant-portal"])

    # -- aggregated pending feed ------------------------------------------

    @router.get("/pending")
    async def list_pending(request: Request) -> dict:
        """Every open pending action across ALL of the owner's campaigns.

        Fans out over the engine's campaigns and merges per-campaign pending
        lists into one feed. Degrades soft: an unreachable engine (or no
        campaigns) returns an empty, well-formed payload with the reachability
        flag so the portal can distinguish "nothing pending" from "offline".
        A single campaign that errors is skipped, not fatal.
        """
        _require_user(request)
        async with ApplicantEngineClient() as engine:
            try:
                campaigns = await engine.list_campaigns()
            except EngineError as exc:
                logger.debug("portal: engine unavailable listing campaigns: %s", exc)
                return {"engine_available": False, "count": 0, "items": []}

            campaign_list = campaigns if isinstance(campaigns, list) else []
            items: list[dict] = []
            for campaign in campaign_list:
                if not isinstance(campaign, dict):
                    continue
                cid = campaign.get("id")
                if not cid:
                    continue
                cid = str(cid)
                cname = _campaign_label(campaign)
                try:
                    data = await engine.list_pending_actions(cid)
                except EngineError as exc:
                    # One campaign failing must not sink the whole feed.
                    logger.debug("portal: pending fetch failed for %s: %s", cid, exc)
                    continue
                raw_items = []
                if isinstance(data, dict):
                    raw_items = data.get("items") or []
                elif isinstance(data, list):
                    raw_items = data
                for raw in raw_items:
                    if isinstance(raw, dict):
                        items.append(_shape_item(raw, campaign_id=cid, campaign_name=cname))

        return {"engine_available": True, "count": len(items), "items": items}

    # -- resolve ----------------------------------------------------------

    @router.post("/actions/{action_id}/resolve")
    async def resolve_action(action_id: str, request: Request) -> dict:
        """Mark one pending action handled once the user has acted on it."""
        _require_user(request)
        async with ApplicantEngineClient() as engine:
            try:
                await engine.resolve_pending_action(action_id)
            except EngineError as exc:
                raise _engine_http_error(exc) from exc
        return {"resolved": True, "action_id": action_id}

    # -- notification center (in-app inbox) -------------------------------

    @router.get("/notifications")
    async def list_notifications(request: Request) -> dict:
        """Current in-app notifications backing the home-base notification center.

        Thin proxy over the engine's in-app inbox. Degrades soft like the pending
        feed: an unreachable engine returns an empty, well-formed payload with the
        reachability flag so the Portal keeps rendering its action rows.
        """
        _require_user(request)
        async with ApplicantEngineClient() as engine:
            try:
                data = await engine.list_notifications()
            except EngineError as exc:
                logger.debug("portal: engine unavailable listing notifications: %s", exc)
                return {"engine_available": False, "count": 0, "items": []}
        items = data.get("items") if isinstance(data, dict) else None
        items = items if isinstance(items, list) else []
        return {"engine_available": True, "count": len(items), "items": items}

    @router.post("/notifications/{notification_id}/seen")
    async def dismiss_notification(notification_id: str, request: Request) -> dict:
        """Dismiss one informational notification so it stops persisting.

        A 404 from the engine (already pruned/cleared) is treated as success so
        the UI can drop the row idempotently instead of erroring.
        """
        _require_user(request)
        async with ApplicantEngineClient() as engine:
            try:
                await engine.dismiss_notification(notification_id)
            except EngineError as exc:
                if exc.status == 404:
                    return {"dismissed": True, "id": notification_id}
                raise _engine_http_error(exc) from exc
        return {"dismissed": True, "id": notification_id}

    # -- supply a missing detail (FR-ATTR-5) ------------------------------

    @router.post("/missing-attribute")
    async def supply_missing_attribute(body: MissingAttributeIn, request: Request) -> dict:
        """Supply a detail the engine flagged as missing and resume the blocked
        application, then clear the originating pending action if one was given.

        Maps to the engine's ``acquire-missing`` endpoint. The engine's confirm
        gate (409) and sensitive-value policy (422) are forwarded so the UI can
        ask the user to confirm. After a successful acquire we best-effort resolve
        the pending action so the row clears without a second round-trip; a resolve
        failure does not undo the successful acquire (it is reported in the body).
        """
        _require_user(request)
        name = (body.name or "").strip()
        value = (body.value or "").strip()
        if not name:
            raise HTTPException(400, "A field name is required")
        if not value:
            raise HTTPException(400, "A value is required")
        async with ApplicantEngineClient() as engine:
            cid = await _resolve_campaign(engine, body.campaign_id)
            payload = {
                "campaign_id": cid,
                "name": name,
                "value": value,
                "confirm": body.confirm,
            }
            try:
                acquired = await engine.acquire_missing_attribute(payload)
            except EngineError as exc:
                raise _engine_http_error(exc) from exc

            resolved = False
            if body.action_id:
                try:
                    await engine.resolve_pending_action(body.action_id)
                    resolved = True
                except EngineError as exc:
                    # The detail was saved; only the row-clear failed. Don't 500 —
                    # report it so the portal can refresh and show the live state.
                    logger.debug("portal: resolve after acquire failed: %s", exc)

        return {
            "acquired": acquired if isinstance(acquired, dict) else {"ok": True},
            "resolved": resolved,
            "campaign_id": cid,
        }

    return router
