"""Notification-center router (FR-UI-3 / FR-NOTIF-1).

The notification *center* is the in-app side of the multi-channel notifier: the
same notifications that fan out to Discord/email (when configured) are always
captured in the notifier's in-app sink, and this router exposes that sink so the
front-door Portal can fold informational notifications in alongside action-
required rows and toast new ones as they arrive.

- ``GET  /api/notifications``            — current in-app notifications. Defaults to today's
  behavior (newest-first, dismissed entries omitted, no cap beyond the notifier's own prune)
  when called with no query params — existing callers (the Portal poll) are unaffected. Optional
  ``include_seen=true`` also returns dismissed entries (undo/history browsing); optional ``since``
  (an ISO-8601 timestamp, matching the ``created_at`` this same endpoint returns) returns only
  entries newer than that cursor so a poller can fetch just what's new; optional ``limit`` bounds
  the page size.
- ``POST /api/notifications/{id}/seen``  — dismiss one informational notification
  so it stops persisting. Action-required notifications are NOT dismissed here;
  they clear when their underlying pending action is resolved (the notifier drops
  the inbox entry on ``expire``), so the center never double-tracks acted items.

Gated behind the LLM-settings gate (FR-UI-5), consistent with the pending-actions
router that backs the same home-base surface.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query

from applicant.app.deps import get_notification_service, require_llm_configured

router = APIRouter(
    prefix="/api/notifications",
    tags=["notifications"],
    dependencies=[Depends(require_llm_configured)],
)


def _shape(entry) -> dict:
    """Normalise one in-app inbox entry into the center's row shape.

    ``kind`` is one of ``action`` | ``digest`` | ``error`` | ``info``. Only
    ``action`` rows link to a pending action (they carry the decision's dedup
    key); the rest are informational and dismissible from the center.
    """
    kind = getattr(entry, "kind", "") or "info"
    created = getattr(entry, "created_at", None)
    dedup = getattr(entry, "dedup_key", None)
    action_ref = ""
    if kind == "action" and dedup and dedup.startswith("decision:"):
        action_ref = dedup.split(":", 1)[1]
    return {
        "id": getattr(entry, "id", "") or "",
        "title": entry.title,
        "body": entry.body,
        "kind": kind,
        "urgency": entry.urgency,
        "deep_link": getattr(entry, "deep_link", None),
        "created_at": created.isoformat() if created is not None else None,
        "links_action": bool(action_ref),
        "action_ref": action_ref,
        "seen": bool(getattr(entry, "seen", False)),
    }


@router.get("")
def list_notifications(
    include_seen: bool = Query(
        False,
        description="Also return dismissed/seen entries (default omits them, unchanged).",
    ),
    since: str | None = Query(
        None,
        description=(
            "Only return entries newer than this ISO-8601 timestamp "
            "(the same shape as each row's created_at)."
        ),
    ),
    limit: int | None = Query(
        None,
        ge=1,
        description="Cap the number of rows returned (newest first).",
    ),
    owner: str | None = Query(
        None,
        description=(
            "Optional caller-identity tag (dark-engine audit lens 10 #28), "
            "forwarded to the notifier for owner-scoped filtering when one "
            "supports it. Omit for the historical, unchanged behavior."
        ),
    ),
    notifications=Depends(get_notification_service),
) -> dict:
    """List the current in-app notifications (newest first).

    With no query params this is exactly the historical behavior (used by the
    Portal's unmodified poll). ``since``/``limit`` let a caller that already
    tracks the newest ``created_at`` it has seen fetch only what's new instead
    of re-shipping the full (up to ~1000-row) inbox every poll. ``owner`` is
    defense-in-depth thread-through only (see
    :meth:`NotificationService.list_inbox`); the real multi-user authorization
    boundary is the workspace's own proxy, which must resolve the caller to
    the engine-owner account before ever reaching this endpoint.
    """
    entries = notifications.list_inbox(include_seen=include_seen, owner=owner)
    if since:
        try:
            cursor = datetime.fromisoformat(since.replace("Z", "+00:00"))
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail="since must be an ISO-8601 timestamp."
            ) from exc
        if cursor.tzinfo is None:
            cursor = cursor.replace(tzinfo=UTC)
        filtered = []
        for entry in entries:
            created = getattr(entry, "created_at", None)
            if created is None or created > cursor:
                filtered.append(entry)
        entries = filtered
    if limit is not None:
        entries = entries[:limit]
    items = [_shape(e) for e in entries]
    return {"count": len(items), "items": items}


@router.post("/deliver-now")
def deliver_now(notifications=Depends(get_notification_service)) -> dict:
    """Release notifications held back by quiet hours, right now (FR-NOTIF-5).

    The "Deliver now" control in Settings: when a quiet window is suppressing
    Discord/email pushes, this force-flushes every pending push immediately so the
    user can pull held approvals/digests without waiting for the window to end.
    Returns the channels that were flushed.
    """
    flushed = notifications.deliver_now()
    return {"flushed": sorted(set(flushed)), "count": len(flushed)}


@router.post("/{notification_id}/seen", status_code=204)
def mark_seen(
    notification_id: str,
    owner: str | None = Query(
        None,
        description=(
            "Optional caller-identity tag (dark-engine audit lens 10 #28), "
            "forwarded to the notifier for owner-scoped filtering when one "
            "supports it. Omit for the historical, unchanged behavior."
        ),
    ),
    notifications=Depends(get_notification_service),
) -> None:
    """Dismiss one informational notification so it stops persisting.

    404 if the id no longer matches a current entry (already pruned/cleared), so
    the caller can drop the row without retrying. ``owner`` is defense-in-depth
    thread-through only (see :meth:`NotificationService.dismiss_notification`);
    the real multi-user authorization boundary is the workspace's own proxy.
    """
    if not notifications.dismiss_notification(notification_id, owner=owner):
        raise HTTPException(status_code=404, detail="That notification is no longer present.")
