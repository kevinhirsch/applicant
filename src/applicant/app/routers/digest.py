"""Digest router (FR-DIG-*, FR-FB-1, FR-NOTIF-2/3).

# STAGE B — owned by Phase 1.

Exposes the DigestReview driving port: build the daily digest (rows + empty-day note),
deliver it across channels (email/webpage + Discord ready-ping), approve a role, and
decline-with-feedback (round-trips into learning + next-run criteria). Also exposes
the web-presence signal that lets the in-app surface pre-empt the Discord push
(FR-NOTIF-2). Services come from the frozen container. Gated behind the LLM gate.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from applicant.app.container import Container
from applicant.app.deps import (
    get_container,
    get_digest_service,
    require_automated_work,
    require_llm_configured,
)

router = APIRouter(
    prefix="/api/digest", tags=["digest"], dependencies=[Depends(require_llm_configured)]
)


class DeclineIn(BaseModel):
    feedback_text: str = ""
    criteria_delta: dict = {}


class PresenceIn(BaseModel):
    present: bool = True


@router.get("")
def index(container: Container = Depends(get_container)) -> dict:
    return {"surface": "digest", "phase": 1, "status": "live"}


@router.get("/{campaign_id}", dependencies=[Depends(require_automated_work)])
def get_digest(campaign_id: str, digest=Depends(get_digest_service)) -> dict:
    """Daily digest payload: one row per viable role + empty-day note (FR-DIG-3/6).

    Building the digest is automated work (scoring + discovery feed it), so it is
    blocked until onboarding + channels + LLM are configured (FR-ONBOARD-2, FR-OOBE-3).
    """
    return digest.build_digest_payload(campaign_id)  # type: ignore[arg-type]


@router.post("/{campaign_id}/deliver", dependencies=[Depends(require_automated_work)])
def deliver(campaign_id: str, digest=Depends(get_digest_service)) -> dict:
    """Deliver the digest: payloads + Discord 'ready' ping + pending items (FR-DIG-2)."""
    result = digest.deliver(campaign_id)  # type: ignore[arg-type]
    return {
        "campaign_id": campaign_id,
        "row_count": len(result["payload"]["rows"]),
        "empty": result["payload"]["empty"],
        "notify_handle": result["notify_handle"],
        "delivered_channels": result["delivered_channels"],
        "email_subject": result["email"]["subject"],
    }


@router.get("/{campaign_id}/email", dependencies=[Depends(require_automated_work)])
def get_email(campaign_id: str, digest=Depends(get_digest_service)) -> dict:
    """The digest email payload (own template, exempt from Applicant style, FR-DIG-2)."""
    return digest.render_email(campaign_id)  # type: ignore[arg-type]


@router.get("/{campaign_id}/weekly-recap", dependencies=[Depends(require_automated_work)])
def get_weekly_recap(campaign_id: str, digest=Depends(get_digest_service)) -> dict:
    """The trailing-7-day recap, read on demand (P1-12 — narrative FE home).

    Pure exposure of the EXISTING recap the scheduler already pushes weekly
    through the notification fan-out (``DigestService.build_weekly_recap`` +
    ``render_weekly_recap_message``, audit Top-25 #18) — no new aggregation
    logic, no new state. Lets the front-door "Daily updates" panel show the
    same first-person, honestly-composed recap sentence at any time instead of
    it existing only as a once-a-week notification. Gated exactly like its
    daily-digest siblings: reading it implies discovery/scoring ran, which is
    automated work.
    """
    recap = digest.build_weekly_recap(campaign_id)  # type: ignore[arg-type]
    return digest.render_weekly_recap_message(campaign_id, recap=recap)  # type: ignore[arg-type]


@router.post("/presence", status_code=204)
def set_presence(body: PresenceIn, container: Container = Depends(get_container)) -> None:
    """Mark the user verifiably present in the web UI (FR-NOTIF-2 pre-empt signal)."""
    notification = container.notification
    if hasattr(notification, "set_presence"):
        notification.set_presence(body.present)


@router.post("/applications/{application_id}/approve", status_code=201)
def approve(application_id: str, digest=Depends(get_digest_service)) -> dict:
    """Approve a digested role; expires other channels (FR-DIG-3, FR-NOTIF-3)."""
    decision = digest.approve(application_id)  # type: ignore[arg-type]
    return {"decision_id": decision.id, "type": decision.type.value}


@router.post("/applications/{application_id}/decline", status_code=201)
def decline(
    application_id: str, body: DeclineIn, digest=Depends(get_digest_service)
) -> dict:
    """Decline-with-feedback; feedback + criteria delta feed learning (FR-DIG-5, FR-FB-1).

    FR-FB-1: blank/whitespace decline feedback is rejected with 422 — feedback is
    mandatory on the decline path.
    """
    try:
        decision = digest.decline(  # type: ignore[arg-type]
            application_id, feedback_text=body.feedback_text, criteria_delta=body.criteria_delta
        )
    except ValueError as exc:
        # 422 Unprocessable Content: mandatory decline feedback was blank (FR-FB-1).
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "decision_id": decision.id,
        "type": decision.type.value,
        "feedback_text": decision.feedback_text,
        "criteria_delta": decision.criteria_delta,
    }
