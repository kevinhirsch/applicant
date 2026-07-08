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
  so a middleware misconfig can't open them up. The aggregated pending feed
  (``GET /pending``, ``GET /pending/count``) and the notification-center
  endpoints (``GET /notifications``, ``POST /notifications/{id}/seen``) are
  gated more strictly by ``_require_notification_owner`` (the shared
  ``src.auth_helpers.require_engine_owner``) instead — the engine is
  single-tenant (no owner concept) for both the pending-actions feed and the
  in-app inbox, so a plain "is someone logged in" check would let any other
  workspace account read/dismiss the real owner's job-search data (security,
  lens 10 #28; DISC-15).
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
from src.auth_helpers import require_engine_owner, require_user

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

    DISC-15: this is now a thin alias for the shared
    :func:`src.auth_helpers.require_engine_owner` gate (factored out of this
    exact implementation so the pending feed and the sibling campaigns/
    tracker/activity proxies can reuse it too) — kept as a named wrapper here
    so the inbox call sites read the same as before.
    """
    return require_engine_owner(request)


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


# The apply-readiness gate the engine computes (``GET /api/setup/status``):
# whether the search can actually run yet (``apply_ready`` / ``automated_work_
# allowed``) and, if not, the plain-language essentials still missing
# (``apply_missing``). The Portal reads this so it can tell the TRUTH about
# whether it's searching, and so its "what's left" list is the SAME one the
# wizard-finish screen and the chat assistant report — never a third, disagreeing
# list. White-label: the engine's ``apply_missing`` labels are already plain
# language (target roles / work mode / locations / salary floor / …), no jargon.
async def _gate_state(engine: ApplicantEngineClient) -> dict:
    """Read the apply-readiness gate, best-effort (never sinks the pending feed).

    Returns ``{}`` when the engine can't answer or is too old to report readiness,
    so the Portal simply omits the gate fields and degrades to its prior behavior.
    """
    reader = getattr(engine, "setup_status", None)
    if not callable(reader):
        return {}
    try:
        raw = await reader()
    except Exception as exc:  # a status hiccup must never break the pending feed
        logger.debug("portal: setup-status read failed: %s", exc)
        return {}
    if not isinstance(raw, dict):
        return {}
    # Conditional inclusion (like apply_ready/apply_missing below): an older engine
    # that omits a key must NOT be reported as a definite ``false`` — the Portal JS
    # treats a MISSING gate field as "unknown" and stays in the calm empty state,
    # whereas ``false`` trips the "your search isn't running yet" alarm. Sending
    # ``bool(raw.get(...))`` here would fabricate that ``false`` and false-alarm.
    out: dict = {}
    if "automated_work_allowed" in raw:
        out["automated_work_allowed"] = bool(raw["automated_work_allowed"])
    if "apply_ready" in raw:
        out["apply_ready"] = bool(raw.get("apply_ready"))
    if "apply_missing" in raw:
        out["apply_missing"] = [
            str(m) for m in (raw.get("apply_missing") or []) if isinstance(m, str)
        ]
    # P1-1 (onboarding TTFV): a plain essentials checklist (model / profile /
    # notifications) derived from the SAME engine status fields the wizard reads
    # (`llm_configured` / `apply_ready`+`apply_missing` / `channels_configured`),
    # so Today can show what's done vs left — with the same conditional-inclusion
    # honesty as above: a field the engine doesn't report is omitted, never
    # fabricated as "not done".
    essentials: list = []
    if "llm_configured" in raw:
        essentials.append(
            {"key": "model", "label": "Connect a model", "done": bool(raw["llm_configured"])}
        )
    if "apply_ready" in raw or "apply_missing" in raw:
        profile_done = bool(raw.get("apply_ready")) or (
            isinstance(raw.get("apply_missing"), list) and not raw["apply_missing"]
        )
        essentials.append(
            {"key": "profile", "label": "Your profile essentials", "done": profile_done}
        )
    if "channels_configured" in raw:
        essentials.append(
            {
                "key": "notifications",
                "label": "Notifications (optional — set up in Settings)",
                "done": bool(raw["channels_configured"]),
            }
        )
    if essentials:
        out["essentials"] = essentials
    return out


def _apply_gap_item(gate: dict, candidates: list) -> Optional[dict]:
    """The single persistent "what's left before your search runs" row, or ``None``.

    Derived from the apply-readiness essentials (``apply_missing``) — the SAME list
    the wizard-finish screen and the chat assistant report — so all three agree.
    Returns ``None`` once the gate is open (the search is genuinely running), when
    readiness is unknown, or when there is no campaign, so the row clears itself.
    ``candidates`` is the list of ``(campaign_id, campaign_name)`` tuples; the row
    attaches to the first so its "Finish setup" jump lands on a real campaign.
    """
    if not gate or not gate.get("apply_missing"):
        return None
    if gate.get("apply_ready") is True or gate.get("automated_work_allowed") is True:
        return None
    cid, cname = candidates[0] if candidates else ("", "")
    item = {
        "id": "onboarding-incomplete",
        "kind": "onboarding_incomplete",
        "title": "Finish setup to start your search",
        "campaign_id": cid,
        "campaign_name": cname,
        "missing": list(gate["apply_missing"]),
        "affordance": "complete",
    }
    # P1-1: carry the essentials checklist (model / profile / notifications) on
    # the row itself so Today's card can render done-vs-left at a glance.
    if gate.get("essentials"):
        item["essentials"] = list(gate["essentials"])
    return item


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

        Owner-scoped (DISC-15, mirrors the notification inbox above): gated
        by :func:`_require_notification_owner` (the shared
        ``require_engine_owner``), not the plain auth-only ``_require_user``
        -- the engine's pending actions are single-tenant, so any other
        workspace account must not be able to read the real owner's feed.
        """
        _require_notification_owner(request)
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
                degraded = soft_degrade(exc, {"count": 0, "items": []})
                # P1-1: on the GATED path (engine reachable, setup unfinished),
                # best-effort attach the essentials checklist so Today's gated
                # state shows exactly what's left, not just a generic message.
                # The status read is ungated, so it usually answers even here.
                if degraded.get("gated"):
                    gate = await _gate_state(engine)
                    if gate.get("essentials"):
                        degraded["essentials"] = gate["essentials"]
                return degraded

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
            # The real apply-readiness gate, so the Portal can tell the truth about
            # whether the search is actually running (product-honesty). A single
            # status read, best-effort — a failure just omits the gate fields.
            gate = await _gate_state(engine)
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

            # One persistent "what's left before your search runs" row, derived from
            # the SAME apply-readiness essentials the wizard-finish screen and the
            # chat assistant report (``apply_missing``) so all three agree. It clears
            # itself once the gate opens (search running). Prepend it atop the feed.
            gap = _apply_gap_item(gate, candidates)
            if gap is not None:
                items.insert(0, gap)

        payload: dict = {"engine_available": True, "count": len(items), "items": items}
        # Surface the gate so the front door renders an HONEST home status: "active /
        # searching" only when automated work is truly allowed, otherwise "not running
        # yet — here's what's left". Absent when the engine couldn't report it.
        payload.update(gate)
        return payload

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

        Deliberately skips the apply-readiness gate read (``_gate_state``) and the
        synthetic "finish setup" gap row it drives — the badge counts only real
        engine pending actions. That one synthetic row still surfaces the moment the
        owner opens the full Portal via ``GET /pending``, so the badge undercounts by
        at most that single row while setup is unfinished, never after.

        Owner-scoped (DISC-15): same gate as ``/pending`` above -- this is the
        same single-tenant pending-actions data, just summed to a count.
        """
        _require_notification_owner(request)
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
