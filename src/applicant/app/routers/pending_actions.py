"""Pending-actions router (FR-UI-3).

# STAGE B — owned by Phase 1.

The pending-actions portal: every item awaiting user input (digest approvals, material
reviews, soft errors, agent questions, final approvals) for a campaign, plus resolve.
Gated behind the LLM-settings gate (FR-UI-5).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from applicant.app.deps import get_pending_actions_service, require_llm_configured

router = APIRouter(
    prefix="/api/pending-actions",
    tags=["pending_actions"],
    dependencies=[Depends(require_llm_configured)],
)


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
def resolve(action_id: str, pending_actions=Depends(get_pending_actions_service)) -> None:
    """Resolve a pending action once the user has acted (FR-UI-3)."""
    pending_actions.resolve(action_id)  # type: ignore[arg-type]
