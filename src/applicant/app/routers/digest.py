"""Digest router (FR-DIG-*, FR-FB-1).

# STAGE B — owned by Phase 1.

Exposes the DigestReview driving port: build the daily digest (rows + empty-day note),
approve a role, and decline-with-feedback. Services are composed from the frozen
container (storage + notification + scoring) so wiring stays in the composition root.
Gated behind the LLM-settings gate (FR-UI-5).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from applicant.app.container import Container
from applicant.app.deps import get_container, require_llm_configured
from applicant.application.services.digest_service import DigestService

router = APIRouter(
    prefix="/api/digest", tags=["digest"], dependencies=[Depends(require_llm_configured)]
)


def _digest_service(container: Container) -> DigestService:
    return DigestService(container.storage, container.notification, container.scoring_service)


class DeclineIn(BaseModel):
    feedback_text: str = ""
    criteria_delta: dict = {}


@router.get("")
def index(container: Container = Depends(get_container)) -> dict:
    return {"surface": "digest", "phase": 1, "status": "live"}


@router.get("/{campaign_id}")
def get_digest(campaign_id: str, container: Container = Depends(get_container)) -> dict:
    """Daily digest payload: one row per viable role + empty-day note (FR-DIG-3/6)."""
    return _digest_service(container).build_digest_payload(campaign_id)  # type: ignore[arg-type]


@router.post("/applications/{application_id}/approve", status_code=201)
def approve(application_id: str, container: Container = Depends(get_container)) -> dict:
    """Approve a digested role (FR-DIG-3)."""
    decision = _digest_service(container).approve(application_id)  # type: ignore[arg-type]
    return {"decision_id": decision.id, "type": decision.type.value}


@router.post("/applications/{application_id}/decline", status_code=201)
def decline(
    application_id: str, body: DeclineIn, container: Container = Depends(get_container)
) -> dict:
    """Decline-with-feedback; feedback + criteria delta feed learning (FR-DIG-5, FR-FB-1)."""
    decision = _digest_service(container).decline(  # type: ignore[arg-type]
        application_id, feedback_text=body.feedback_text, criteria_delta=body.criteria_delta
    )
    return {
        "decision_id": decision.id,
        "type": decision.type.value,
        "feedback_text": decision.feedback_text,
        "criteria_delta": decision.criteria_delta,
    }
