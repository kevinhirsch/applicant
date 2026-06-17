"""Notification-center router (FR-UI-3 / FR-NOTIF-1).

The notification *center* is the in-app side of the multi-channel notifier: the
same notifications that fan out to Discord/email (when configured) are always
captured in the notifier's in-app sink, and this router exposes that sink so the
front-door Portal can fold informational notifications in alongside action-
required rows and toast new ones as they arrive.

- ``GET  /api/notifications``            — current in-app notifications.
- ``POST /api/notifications/{id}/seen``  — dismiss one informational notification
  so it stops persisting. Action-required notifications are NOT dismissed here;
  they clear when their underlying pending action is resolved (the notifier drops
  the inbox entry on ``expire``), so the center never double-tracks acted items.

Gated behind the LLM-settings gate (FR-UI-5), consistent with the pending-actions
router that backs the same home-base surface.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

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
def list_notifications(notifications=Depends(get_notification_service)) -> dict:
    """List the current in-app notifications (newest first)."""
    entries = notifications.list_inbox()
    items = [_shape(e) for e in entries]
    return {"count": len(items), "items": items}


@router.post("/{notification_id}/seen", status_code=204)
def mark_seen(notification_id: str, notifications=Depends(get_notification_service)) -> None:
    """Dismiss one informational notification so it stops persisting.

    404 if the id no longer matches a current entry (already pruned/cleared), so
    the caller can drop the row without retrying.
    """
    if not notifications.dismiss_notification(notification_id):
        raise HTTPException(status_code=404, detail="That notification is no longer present.")
