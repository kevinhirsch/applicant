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
  so a middleware misconfig can't open them up. The notification-center
  endpoints (``GET /notifications``, ``POST /notifications/{id}/seen``) are
  gated more strictly by ``_require_notification_owner`` instead — the engine
  inbox is single-tenant (no owner concept), so a plain "is someone logged in"
  check would let any other workspace account read/dismiss the real owner's
  job-search notifications (security, lens 10 #28).
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

import asyncio
import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from src.applicant_engine import (
    ApplicantEngineClient,
    EngineError,
    shared_engine_http_client,
    soft_degrade,
)
from src.auth_helpers import get_current_user, is_trusted_loopback, require_user

logger = logging.getLogger(__name__)


# --- request bodies ---------------------------------------------------------


class MissingAttributeIn(BaseModel):
    """Supply a value for a detail the engine flagged as missing (FR-ATTR-5)."""

    name: str
    value: str
    campaign_id: Optional[str] = None
    action_id: Optional[str] = None
    confirm: bool = False


class BulkResolveIn(BaseModel):
    """Resolve a batch of pending actions — "approve all N items" (#295)."""

    campaign_id: str
    action_ids: list[str]


class SnoozeIn(BaseModel):
    """Reschedule a pending action — "remind me later" (#295).

    ``until`` is an explicit ISO wake time; otherwise ``hours`` (default ~24, i.e.
    "remind me tomorrow") sets it relative to now.
    """

    until: Optional[str] = None
    hours: Optional[float] = None


# --- helpers ----------------------------------------------------------------


def _require_user(request: Request) -> str:
    """Require an authenticated owner (the global gate also enforces this)."""
    return require_user(request)


def _require_notification_owner(request: Request) -> str:
    """Require the engine-owner account for the notification inbox (security,
    lens 10 #28).

    The engine has no owner concept at all (single-tenant per deployment):
    every in-app inbox entry — title, body, deep link, all of it — belongs to
    the ONE person this Applicant instance was set up for, not to whichever
    workspace account happens to be logged in. Plain ``require_user`` (any
    authenticated user) was letting a second, unrelated workspace account read
    and dismiss that owner's job-search notifications (titles include role/
    company).

    Mirrors ``applicant_admin_routes.py``'s ``_require_admin`` exactly — the
    one place in this proxy layer that already distinguishes "the specific
    owner" from "any authenticated user": in single-user / unconfigured mode
    there is no admin distinction, so the lone owner passes (matching the rest
    of the workspace); once the workspace is configured for MULTIPLE accounts,
    only an admin may reach the notification center. Fails closed: any failure
    resolving admin status denies rather than allows.
    """
    owner = get_current_user(request)
    auth_mgr = getattr(request.app.state, "auth_manager", None)
    configured = bool(getattr(auth_mgr, "is_configured", False)) if auth_mgr else False

    if not configured:
        # Single-user / first-run: no admin distinction, but only from a DIRECT
        # loopback connection when there is no session at all (mirrors
        # ``_require_admin``'s #228 hardening below).
        if owner:
            return owner
        if is_trusted_loopback(request):
            return ""
        raise HTTPException(status_code=401, detail="Not authenticated")

    if not owner:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        is_admin = bool(auth_mgr.is_admin(owner))
    except Exception:  # defensive: never fail open on the gate itself
        is_admin = False
    if not is_admin:
        raise HTTPException(
            status_code=403,
            detail="Your account can't access this job search's notifications.",
        )
    return owner


def _engine_http_error(exc: EngineError) -> HTTPException:
    """Translate a typed :class:`EngineError` into an HTTPException for a *write*.

    A transport-level failure (no ``status``) means the engine is unreachable →
    503. 4xx responses are forwarded (client-correctable: 409 confirm gate,
    422 validation). 5xx responses are scrubbed — raw detail may contain internal
    stack traces or state; logged server-side and a generic message returned.
    """
    if exc.status is None:
        return HTTPException(
            status_code=503,
            detail="The Applicant engine is unavailable right now. Please try again shortly.",
        )
    if exc.status >= 500:
        logger.warning("engine 5xx (portal): status=%s detail=%s", exc.status, exc.detail or exc.message)
        return HTTPException(status_code=502, detail="The Applicant engine returned an error.")
    detail = exc.detail if exc.detail not in (None, "") else exc.message
    return HTTPException(status_code=exc.status, detail=detail)


def _campaign_label(campaign: dict) -> str:
    """Best human label for a campaign dict from the engine."""
    return str(campaign.get("name") or campaign.get("id") or "")


# Plain-language labels for the engine's required intake sections, so the
# "finish your profile" gap row names the SPECIFIC steps still to do instead of
# raw codes. White-label: no FR-/NFR- jargon, no codenames.
_SECTION_LABELS: dict[str, str] = {
    "identity": "Identity",
    "work_authorization": "Work authorization",
    "location": "Location",
    "target_roles": "Target roles",
    "compensation": "Compensation",
    "work_history": "Work history",
    "education": "Education",
    "references": "References",
    "key_attributes": "Key attributes",
    "eeo": "EEO (optional)",
    "base_resume": "Base résumé",
    "campaign_criteria": "Campaign criteria",
}


def _section_label(code: str) -> str:
    """Friendly label for a section code; falls back to a title-cased code."""
    code = str(code or "")
    return _SECTION_LABELS.get(code, code.replace("_", " ").strip().capitalize() or code)


async def _onboarding_gap_item(
    engine: ApplicantEngineClient, campaign_list: list[dict]
) -> Optional[dict]:
    """Build the single persistent "finish your profile" row, or ``None``.

    Reuses the engine's existing onboarding state (no new detection): for the
    owner's campaigns, the first one whose intake still has missing sections
    yields one synthetic pending item naming those specific steps. Returns
    ``None`` when every campaign is complete (so the row clears on its own) or
    when there is no campaign / the engine can't answer.

    Perf lens 03, item #4: the per-campaign ``onboarding_state`` reads are fanned
    out with ``asyncio.gather`` instead of one-at-a-time awaits. The loop bodies
    are independent (each campaign's state is fetched and evaluated on its own —
    the only cross-iteration coupling was "return the first incomplete one",
    which is a short-circuit *optimization*, not a data dependency), so gathering
    every campaign first and then picking the first incomplete one in the
    original ``campaign_list`` order yields the identical result deterministically.
    """
    candidates = [
        (campaign, str(campaign.get("id")))
        for campaign in campaign_list
        if isinstance(campaign, dict) and campaign.get("id")
    ]
    if not candidates:
        return None
    states = await asyncio.gather(
        *(engine.onboarding_state(cid) for _campaign, cid in candidates),
        return_exceptions=True,
    )
    for (campaign, cid), state in zip(candidates, states):
        if isinstance(state, BaseException):
            # Onboarding state is best-effort context for the gap row; a single
            # failure must not sink the feed. Skip this campaign and try the next.
            logger.debug("portal: onboarding state failed for %s: %s", cid, state)
            continue
        if not isinstance(state, dict):
            continue
        if state.get("complete"):
            continue
        missing = state.get("missing_sections") or []
        missing = [str(s) for s in missing if isinstance(s, (str,))]
        if not missing:
            continue
        return {
            "id": "onboarding-incomplete",
            "kind": "onboarding_incomplete",
            "title": "Finish your profile",
            "campaign_id": cid,
            "campaign_name": _campaign_label(campaign),
            "missing": [_section_label(code) for code in missing],
            "missing_codes": missing,
            "affordance": "complete",
        }
    return None


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
        # Proof-of-concept for perf lens #3 (shared httpx client): this is the
        # highest-traffic proxy route (the Portal badge poll + open), fanning
        # out over every campaign — ride the app-lifetime pooled connection
        # (workspace/app.py's ``app.state.http_client``) instead of a fresh
        # pool per poll. `shared_engine_http_client` returns None (⇒ unchanged
        # private-pool behaviour) when the shared client isn't set up.
        async with ApplicantEngineClient(client=shared_engine_http_client(request)) as engine:
            try:
                campaigns = await engine.list_campaigns()
            except EngineError as exc:
                logger.debug("portal: campaigns read failed (status=%s): %s", exc.status, exc)
                # A client-correctable setup gate (e.g. 409 automated-work gate) is
                # NOT offline: forward the engine's plain-language message so the
                # Portal shows the honest setup prompt, not "not connected yet".
                return soft_degrade(exc, {"count": 0, "items": []})

            campaign_list = campaigns if isinstance(campaigns, list) else []
            items: list[dict] = []
            # Perf lens 03, item #4: this was a SEQUENTIAL `await` per campaign
            # (M serial engine hops on the highest-traffic route). The loop bodies
            # are independent — each campaign's pending list is fetched and shaped
            # on its own, with no ordering dependency between iterations — so fan
            # them out with asyncio.gather. gather() preserves result order to
            # match the input order, so the merged `items` list comes out in the
            # exact same campaign-by-campaign order the old sequential loop produced.
            candidates = [
                (str(campaign.get("id")), _campaign_label(campaign))
                for campaign in campaign_list
                if isinstance(campaign, dict) and campaign.get("id")
            ]
            if candidates:
                results = await asyncio.gather(
                    *(engine.list_pending_actions(cid) for cid, _cname in candidates),
                    return_exceptions=True,
                )
                for (cid, cname), data in zip(candidates, results):
                    if isinstance(data, BaseException):
                        # One campaign failing must not sink the whole feed.
                        logger.debug("portal: pending fetch failed for %s: %s", cid, data)
                        continue
                    raw_items = []
                    if isinstance(data, dict):
                        raw_items = data.get("items") or []
                    elif isinstance(data, list):
                        raw_items = data
                    for raw in raw_items:
                        if isinstance(raw, dict):
                            items.append(_shape_item(raw, campaign_id=cid, campaign_name=cname))

            # One persistent "finish your profile" row when the owner's intake is
            # incomplete, naming the SPECIFIC missing steps. It clears on its own
            # once every required section is filled (missing_sections empty), so it
            # needs no emit/clear lifecycle. Prepend it so it sits atop the feed.
            gap = await _onboarding_gap_item(engine, campaign_list)
            if gap is not None:
                items.insert(0, gap)

        return {"engine_available": True, "count": len(items), "items": items}

    # -- lightweight badge count -------------------------------------------

    @router.get("/pending/count")
    async def pending_count(request: Request) -> dict:
        """Just the total pending count across the owner's campaigns.

        Perf lens 03, item #5: the badge poll (every 60s, `applicantPortal.js`
        ``refreshBadge``) used to call ``GET /pending`` — the full aggregated
        feed (shaped rows + the onboarding-gap fan-out) — just to read
        ``count``. This calls the engine's sibling ``GET
        /api/pending-actions/{campaign_id}/count`` (an integer-only response)
        concurrently across campaigns via ``asyncio.gather`` and sums them.

        Deliberately skips the onboarding-gap detection walk
        (``_onboarding_gap_item``'s per-campaign ``onboarding_state`` reads) —
        that is exactly the fan-out this endpoint exists to avoid paying every
        60s. A "finish your profile" gap (if any) still surfaces the moment the
        owner opens the full Portal via ``GET /pending``, so the badge undercounts
        by at most that one synthetic row while unconfigured, never after.
        """
        _require_user(request)
        async with ApplicantEngineClient() as engine:
            try:
                campaigns = await engine.list_campaigns()
            except EngineError as exc:
                logger.debug(
                    "portal: campaigns read failed for badge count (status=%s): %s",
                    exc.status,
                    exc,
                )
                return soft_degrade(exc, {"count": 0})

            campaign_list = campaigns if isinstance(campaigns, list) else []
            cids = [
                str(campaign.get("id"))
                for campaign in campaign_list
                if isinstance(campaign, dict) and campaign.get("id")
            ]
            if not cids:
                return {"engine_available": True, "count": 0}

            results = await asyncio.gather(
                *(engine._request("GET", f"/api/pending-actions/{cid}/count") for cid in cids),
                return_exceptions=True,
            )

        total = 0
        for cid, result in zip(cids, results):
            if isinstance(result, BaseException):
                logger.debug("portal: pending count fetch failed for %s: %s", cid, result)
                continue
            n = result.get("count") if isinstance(result, dict) else None
            if isinstance(n, int):
                total += n

        return {"engine_available": True, "count": total}

    # -- resolve ----------------------------------------------------------

    @router.post("/actions/{action_id}/resolve")
    async def resolve_action(action_id: str, request: Request) -> dict:
        """Mark one pending action handled once the user has acted on it.

        An optional JSON body (e.g. ``{"apply": true}``) is forwarded so a held
        integral change can be confirmed/applied before the item clears (FR-FB-3).
        """
        _require_user(request)
        try:
            body = await request.json()
        except Exception:
            logger.warning("Bare exception in applicant_portal_routes.py")
            body = None
        if not isinstance(body, dict):
            body = None
        async with ApplicantEngineClient() as engine:
            try:
                await engine.resolve_pending_action(action_id, body)
            except EngineError as exc:
                raise _engine_http_error(exc) from exc
        return {"resolved": True, "action_id": action_id}

    # -- bulk resolve ("approve all N") -----------------------------------

    @router.post("/actions/resolve-bulk")
    async def resolve_actions_bulk(body: BulkResolveIn, request: Request) -> dict:
        """Resolve many pending actions in one call — "approve all N items" (#295).

        Thin proxy over the engine's batch resolve, which campaign-scopes the ids
        (anything not belonging to ``campaign_id`` is skipped). Returns the ids
        actually cleared so the UI can drop exactly those rows.
        """
        _require_user(request)
        cid = (body.campaign_id or "").strip()
        if not cid:
            raise HTTPException(400, "A job-search workspace id is required")
        ids = [i for i in (body.action_ids or []) if i]
        if not ids:
            return {"resolved": [], "skipped": [], "resolved_count": 0}
        async with ApplicantEngineClient() as engine:
            try:
                data = await engine.resolve_pending_actions_bulk(cid, ids)
            except EngineError as exc:
                raise _engine_http_error(exc) from exc
        data = data if isinstance(data, dict) else {}
        return {
            "resolved": data.get("resolved", []),
            "skipped": data.get("skipped", []),
            "resolved_count": data.get("resolved_count", len(data.get("resolved", []))),
        }

    # -- snooze ("remind me later") ---------------------------------------

    @router.post("/actions/{action_id}/snooze")
    async def snooze_action(action_id: str, body: SnoozeIn, request: Request) -> dict:
        """Reschedule a pending action so it drops off the home base until due (#295).

        Forwards an optional wake time (``until`` ISO or ``hours``) to the engine; a
        bare call defers ~24h ("remind me tomorrow"). A 404 (already resolved/gone)
        is forwarded so the UI can drop the row.
        """
        _require_user(request)
        payload: dict = {}
        if body.until:
            payload["until"] = body.until
        if body.hours is not None:
            payload["hours"] = body.hours
        async with ApplicantEngineClient() as engine:
            try:
                data = await engine.snooze_pending_action(action_id, payload or None)
            except EngineError as exc:
                raise _engine_http_error(exc) from exc
        data = data if isinstance(data, dict) else {}
        return {
            "action_id": action_id,
            "snoozed_until": data.get("snoozed_until"),
        }

    # -- notification center (in-app inbox) -------------------------------

    @router.get("/notifications")
    async def list_notifications(request: Request) -> dict:
        """Current in-app notifications backing the home-base notification center.

        Thin proxy over the engine's in-app inbox. Degrades soft like the pending
        feed: an unreachable engine returns an empty, well-formed payload with the
        reachability flag so the Portal keeps rendering its action rows.

        Owner-scoped (security, lens 10 #28): gated by
        :func:`_require_notification_owner`, not the plain auth-only
        ``_require_user`` — titles/bodies include role/company, so any other
        workspace account must not be able to read them.
        """
        _require_notification_owner(request)
        async with ApplicantEngineClient() as engine:
            try:
                data = await engine.list_notifications()
            except EngineError as exc:
                logger.debug("portal: notifications read failed (status=%s): %s", exc.status, exc)
                return soft_degrade(exc, {"count": 0, "items": []})
        items = data.get("items") if isinstance(data, dict) else None
        items = items if isinstance(items, list) else []
        return {"engine_available": True, "count": len(items), "items": items}

    @router.post("/notifications/deliver-now")
    async def deliver_notifications_now(request: Request) -> dict:
        """Release notifications held back by quiet hours, right now (FR-NOTIF-5).

        Thin proxy over the engine's force-flush so the Settings "Deliver now"
        control can release held Discord/email pushes without waiting for the quiet
        window to end. Degrades soft when the engine is unreachable.
        """
        _require_user(request)
        async with ApplicantEngineClient() as engine:
            try:
                data = await engine.deliver_notifications_now()
            except EngineError as exc:
                logger.debug("portal: deliver-now failed (status=%s): %s", exc.status, exc)
                return soft_degrade(exc, {"flushed": [], "count": 0})
        flushed = data.get("flushed") if isinstance(data, dict) else None
        flushed = flushed if isinstance(flushed, list) else []
        return {"engine_available": True, "flushed": flushed, "count": len(flushed)}

    @router.post("/notifications/{notification_id}/seen")
    async def dismiss_notification(notification_id: str, request: Request) -> dict:
        """Dismiss one informational notification so it stops persisting.

        A 404 from the engine (already pruned/cleared) is treated as success so
        the UI can drop the row idempotently instead of erroring.

        Owner-scoped (security, lens 10 #28): gated by
        :func:`_require_notification_owner`, matching the read above — a
        non-owner workspace account must not be able to dismiss the owner's
        pending notifications either.
        """
        _require_notification_owner(request)
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
