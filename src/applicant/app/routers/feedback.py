"""Feedback router (FR-FB-1/2/3).

Free-text/chat feedback at any time and a guided survey, both feeding per-campaign
learning (FR-FB-2, FR-LEARN-3). Survey answers cross-reference the attribute cloud,
honoring the confirmation gate for integral changes (FR-FB-3). Gated behind the LLM
gate (FR-UI-5).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from applicant.app.container import Container
from applicant.app.deps import get_container, require_llm_configured

router = APIRouter(
    prefix="/api/feedback", tags=["feedback"], dependencies=[Depends(require_llm_configured)]
)


class FreeTextIn(BaseModel):
    campaign_id: str
    text: str
    criteria_delta: dict = {}


class SurveyIn(BaseModel):
    campaign_id: str
    answers: dict[str, str] = {}


@router.get("")
def index() -> dict:
    return {"surface": "feedback", "phase": 1, "status": "live"}


@router.post("/freetext", status_code=201)
def freetext(body: FreeTextIn, container: Container = Depends(get_container)) -> dict:
    """Free-text/chat feedback folded into learning (FR-FB-2)."""
    return container.feedback_service.submit_freetext(
        body.campaign_id,  # type: ignore[arg-type]
        body.text,
        criteria_delta=body.criteria_delta,
    )


@router.post("/survey", status_code=201)
def survey(body: SurveyIn, container: Container = Depends(get_container)) -> dict:
    """Guided survey folded into learning + attribute cloud (FR-FB-2/3)."""
    return container.feedback_service.submit_survey(
        body.campaign_id, body.answers  # type: ignore[arg-type]
    )
