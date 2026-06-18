"""Pending-actions router (FR-UI-3).

# STAGE B — owned by Phase 1.

The pending-actions portal: every item awaiting user input (digest approvals, material
reviews, soft errors, agent questions, final approvals) for a campaign, plus resolve.
Gated behind the LLM-settings gate (FR-UI-5).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from applicant.app.deps import (
    get_attribute_cloud_service,
    get_pending_actions_service,
    require_llm_configured,
)
from applicant.application.services.pending_actions_service import KIND_INTEGRAL_CHANGE
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


@router.get("")
def index() -> dict:
    return {"surface": "pending_actions", "phase": 1, "status": "live"}


@router.get("/{campaign_id}")
def list_pending(campaign_id: str, pending_actions=Depends(get_pending_actions_service)) -> dict:
    """List open pending actions for the campaign (FR-UI-3) — the 24/7 home base."""
    actions = pending_actions.list_pending(campaign_id)  # type: ignore[arg-type]
    return {
        "campaign_id": campaign_id,
        "count": len(actions),
        "items": [
            {
                "id": a.id,
                "kind": a.kind,
                "title": a.title,
                "application_id": a.application_id,
                "payload": a.payload,
                "created_at": a.created_at.isoformat(),
            }
            for a in actions
        ],
    }


@router.post("/{action_id}/resolve", status_code=204)
def resolve(
    action_id: str,
    body: ResolveIn | None = None,
    pending_actions=Depends(get_pending_actions_service),
    attribute_cloud=Depends(get_attribute_cloud_service),
) -> None:
    """Resolve a pending action once the user has acted (FR-UI-3).

    For a held integral change (``integral_change``), ``apply=true`` commits the
    proposed value through the confirmation gate (the user is the confirmer, so this
    is the explicit confirmation FR-FB-3 requires) before clearing the item;
    ``apply=false`` / absent rejects it and just clears the item. All other kinds
    ignore the body and resolve as before.
    """
    aid = PendingActionId(action_id)
    action = pending_actions.get(aid)
    if (
        action is not None
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
    pending_actions.resolve(aid)
