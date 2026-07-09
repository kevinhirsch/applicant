"""Pending-actions router (FR-UI-3).

# STAGE B — owned by Phase 1.

The pending-actions portal: every item awaiting user input (digest approvals, material
reviews, soft errors, agent questions, final approvals) for a campaign, plus resolve.
Gated behind the LLM-settings gate (FR-UI-5).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from applicant.app.deps import (
    get_attribute_cloud_service,
    get_notification_service,
    get_pending_actions_service,
    require_llm_configured,
)
from applicant.application.services.pending_actions_service import (
    KIND_INTEGRAL_CHANGE,
    RESOLVE_ALREADY_RESOLVED,
)
from applicant.core.ids import PendingActionId

router = APIRouter(
    prefix="/api/pending-actions",
    tags=["pending_actions"],
    dependencies=[Depends(require_llm_configured)],
)


class ResolveIn(BaseModel):
    """Optional resolve payload. For an ``integral_change`` item, ``apply=True``
    commits the held change before resolving; ``False`` (or absent) just clears it."""

    apply: bool | None = None


class BulkResolveIn(BaseModel):
    """Resolve a batch of pending actions in one call (#295 bulk action).

    ``action_ids`` are resolved only if they belong to the path campaign and are
    still open — anything else is skipped so a caller can't clear another
    campaign's items by id.
    """

    action_ids: list[str]


class SnoozeIn(BaseModel):
    """Reschedule a pending action — "remind me later" (#295 snooze).

    ``until`` is an explicit ISO wake time; otherwise ``hours`` (default 24, i.e.
    "remind me tomorrow") sets it relative to now.
    """

    until: str | None = None
    hours: float | None = None


@router.get("")
def index() -> dict:
    return {"surface": "pending_actions", "phase": 1, "status": "live"}


def _ladder_status_for(payload: dict | None, notifications) -> dict | None:
    """Best-effort escalation-ladder lookup for one pending action (#77).

    ``payload["dedup_key"]`` is only present when the item was materialized with
    an explicit dedup key that also matches the ref its notification was fired
    with (e.g. ``material_service._announce_review_ready`` uses
    ``f"material_review:{doc.id}"`` for BOTH). Never raises — a lookup failure
    (or a notifier that doesn't support introspection) degrades to ``None`` so it
    can never break the pending-actions list.
    """
    ref = (payload or {}).get("dedup_key")
    if not ref:
        return None
    try:
        return notifications.ladder_status(str(ref))
    except Exception:  # pragma: no cover - defensive: read-only, never break the page
        return None


@router.get("/{campaign_id}")
def list_pending(
    campaign_id: str,
    include_snoozed: bool = False,
    pending_actions=Depends(get_pending_actions_service),
    notifications=Depends(get_notification_service),
) -> dict:
    """List open pending actions for the campaign (FR-UI-3) — the 24/7 home base.

    Each item is a first-class *task* (#295): besides the raw fields it carries
    derived task metadata — time-in-state (aging), an urgency flag, a coarse
    ``priority`` (items are returned highest-priority-first), and snooze state.
    Snoozed items ("remind me later") are hidden until due unless
    ``include_snoozed=true``.
    """
    paired = pending_actions.list_with_metadata(  # type: ignore[arg-type]
        campaign_id, include_snoozed=include_snoozed
    )
    return {
        "campaign_id": campaign_id,
        "count": len(paired),
        "items": [
            {
                "id": a.id,
                "kind": a.kind,
                "title": a.title,
                "application_id": a.application_id,
                "campaign_id": a.campaign_id,
                "payload": a.payload,
                "created_at": a.created_at.isoformat(),
                **meta,
                # dark-engine audit #77: the notification escalation-ladder state
                # (held vs. escalated, which rung/channel is next, when) for the item
                # -- reused from the payload's own ``dedup_key`` where present (the
                # SAME ref ``notify_decision`` fired the ladder with, e.g.
                # ``material_review:{doc_id}``), so this never invents a mapping.
                # ``None`` when the item's payload carries no dedup_key (most kinds
                # notify via an immediate/CRITICAL ping with no ladder to hold) or
                # nothing is currently active for it.
                "notification_ladder": _ladder_status_for(a.payload, notifications),
            }
            for a, meta in paired
        ],
    }


@router.get("/{campaign_id}/count")
def count_pending(
    campaign_id: str,
    include_snoozed: bool = False,
    pending_actions=Depends(get_pending_actions_service),
) -> dict:
    """Just the open-pending count for the campaign (perf lens 03, item #5).

    A sibling of ``GET /{campaign_id}`` for callers that only need an integer —
    e.g. the workspace badge poll, which previously downloaded the full pending
    payload (shaped rows + task metadata) every 60s just to set a count. This
    route skips the per-item :mod:`applicant.core.task_metadata` derivation and
    full-row serialization; reserve the full list for when the portal is
    actually opened.
    """
    return {
        "campaign_id": campaign_id,
        "count": pending_actions.count_pending(  # type: ignore[arg-type]
            campaign_id, include_snoozed=include_snoozed
        ),
    }


@router.post("/{campaign_id}/resolve-bulk")
def resolve_bulk(
    campaign_id: str,
    body: BulkResolveIn,
    pending_actions=Depends(get_pending_actions_service),
) -> dict:
    """Resolve many pending actions at once — e.g. "approve all N digest items" (#295).

    Campaign-scoped in the service: ids that don't belong to ``campaign_id`` (or are
    already resolved / unknown) are skipped, not resolved.
    """
    ids = [PendingActionId(i) for i in body.action_ids]
    result = pending_actions.resolve_many(campaign_id, ids)  # type: ignore[arg-type]
    return {
        "campaign_id": campaign_id,
        "resolved": result["resolved"],
        "skipped": result["skipped"],
        "resolved_count": len(result["resolved"]),
    }


@router.post("/{action_id}/snooze")
def snooze(
    action_id: str,
    body: SnoozeIn | None = None,
    pending_actions=Depends(get_pending_actions_service),
) -> dict:
    """Reschedule a pending action — "remind me tomorrow" (#295 snooze).

    Hides the item from the home base until it comes due, then it re-appears. The
    notification escalation is driven off the same open-action set, so snoozing an
    item also defers its re-notification until the wake time.
    """
    until_dt = None
    hours = None
    if body is not None:
        hours = body.hours
        if body.until:
            from datetime import datetime as _dt

            try:
                until_dt = _dt.fromisoformat(body.until.replace("Z", "+00:00"))
            except ValueError as exc:
                raise HTTPException(status_code=422, detail="Invalid 'until' timestamp.") from exc
    updated = pending_actions.snooze(PendingActionId(action_id), until=until_dt, hours=hours)
    if updated is None:
        raise HTTPException(status_code=404, detail="That item is no longer open.")
    return {
        "action_id": action_id,
        "snoozed_until": (updated.payload or {}).get("snoozed_until"),
    }


@router.post("/{action_id}/resolve")
def resolve(
    action_id: str,
    body: ResolveIn | None = None,
    pending_actions=Depends(get_pending_actions_service),
    attribute_cloud=Depends(get_attribute_cloud_service),
) -> Response:
    """Resolve a pending action once the user has acted (FR-UI-3).

    For a held integral change (``integral_change``), ``apply=true`` commits the
    proposed value through the confirmation gate (the user is the confirmer, so this
    is the explicit confirmation FR-FB-3 requires) before clearing the item;
    ``apply=false`` / absent rejects it and just clears the item. All other kinds
    ignore the body and resolve as before.

    DISC-6: a genuine open→resolved transition still returns a bare ``204`` (as
    before, so existing callers are unaffected), but an already-resolved action
    (two tabs, a retried request, a stale client re-sending the same id) now
    gets a distinguishable ``200`` body instead of looking identical to a fresh
    resolve — the service (lens 04 #27) already computes this outcome, it just
    wasn't surfaced past this router. Wired through to the workspace proxy and
    Portal JS so the user sees an honest "already handled" instead of a silent
    no-op.
    """
    aid = PendingActionId(action_id)
    action = pending_actions.get(aid)
    if (
        action is not None
        and not action.resolved
        and action.kind == KIND_INTEGRAL_CHANGE
        and body is not None
        and body.apply
    ):
        payload = action.payload or {}
        name = payload.get("attribute_name")
        value = payload.get("proposed_value")
        if name and value is not None:
            attribute_cloud.upsert(
                action.campaign_id, name, str(value), is_integral=True, confirm=True
            )
    outcome = pending_actions.resolve(aid)
    if outcome == RESOLVE_ALREADY_RESOLVED:
        return JSONResponse(
            status_code=200,
            content={"action_id": action_id, "status": "already_resolved"},
        )
    return Response(status_code=204)
