"""Audit-log export router (FR-LOG-4, FR-OBS-2).

GET /api/admin/audit-log/{campaign_id}/export.json
    → ordered ActionEvents for a campaign, Content-Disposition: attachment.

GET /api/admin/audit-log/application/{application_id}/export.json
    → ordered ActionEvents for one application, Content-Disposition: attachment.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from applicant.app.deps import get_storage, require_llm_configured
from applicant.core.ids import ApplicationId, CampaignId

router = APIRouter(
    prefix="/api/admin/audit-log",
    tags=["audit"],
    dependencies=[Depends(require_llm_configured)],
)


def _serialise_event(ev) -> dict:
    """Convert an ActionEvent to a JSON-safe dict."""
    occurred = ev.occurred_at
    if isinstance(occurred, datetime):
        occurred = occurred.isoformat()
    return {
        "id": str(ev.id),
        "occurred_at": occurred,
        "application_id": str(ev.application_id) if ev.application_id else None,
        "campaign_id": str(ev.campaign_id) if ev.campaign_id else None,
        "actor": ev.actor,
        "action": ev.action,
        "reason": ev.reason,
        "context": ev.context or {},
    }


def _export_response(events: list) -> Response:
    data = {
        "exported_at": datetime.now(UTC).isoformat(),
        "count": len(events),
        "events": [_serialise_event(e) for e in events],
    }
    body = json.dumps(data, indent=2, ensure_ascii=False)
    return Response(
        content=body,
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=audit-log.json"},
    )


@router.get("/{campaign_id}/export.json")
def export_campaign_audit_log(
    campaign_id: str,
    storage=Depends(get_storage),
) -> Response:
    """Export the full ordered action trail for a campaign as a downloadable JSON file."""
    try:
        cid = CampaignId(campaign_id)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid campaign ID") from exc

    events = storage.action_events.list_for_campaign(cid)
    return _export_response(events)


@router.get("/application/{application_id}/export.json")
def export_application_audit_log(
    application_id: str,
    storage=Depends(get_storage),
) -> Response:
    """Export the full ordered action trail for one application as a downloadable JSON file."""
    try:
        aid = ApplicationId(application_id)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid application ID") from exc

    events = storage.action_events.list_for_application(aid)
    return _export_response(events)
