"""Feedback router (FR-FB-1/2/3).

Free-text/chat feedback at any time and a guided survey, both feeding per-campaign
learning (FR-FB-2, FR-LEARN-3). Survey answers cross-reference the attribute cloud,
honoring the confirmation gate for integral changes (FR-FB-3). ``/ingest`` bulk-
reconciles a whole batch of parsed/observed facts in one call (FR-LEARN-4,
dark-engine audit #42) via ``FeedbackService.ingest_parsed_input``'s list path:
non-integral values auto-apply, integral ones are held for confirmation, conflicts
are surfaced, and sensitive (EEO) fields are skipped. Gated behind the LLM gate
(FR-UI-5).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from applicant.app.deps import get_feedback_service, require_llm_configured

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


class ObservationIn(BaseModel):
    """One observed/parsed fact: ``{name, value, source?, is_integral?}``."""

    name: str
    value: str
    source: str = "input"
    is_integral: bool = False


class IngestIn(BaseModel):
    observations: list[ObservationIn] = []


@router.get("")
def index() -> dict:
    return {"surface": "feedback", "phase": 1, "status": "live"}


@router.post("/freetext", status_code=201)
def freetext(body: FreeTextIn, feedback=Depends(get_feedback_service)) -> dict:
    """Free-text/chat feedback folded into learning (FR-FB-2)."""
    return feedback.submit_freetext(
        body.campaign_id,  # type: ignore[arg-type]
        body.text,
        criteria_delta=body.criteria_delta,
    )


@router.post("/survey", status_code=201)
def survey(body: SurveyIn, feedback=Depends(get_feedback_service)) -> dict:
    """Guided survey folded into learning + attribute cloud (FR-FB-2/3)."""
    return feedback.submit_survey(
        body.campaign_id, body.answers  # type: ignore[arg-type]
    )


@router.post("/{campaign_id}/ingest", status_code=201)
def ingest(
    campaign_id: str, body: IngestIn, feedback=Depends(get_feedback_service)
) -> dict:
    """Bulk-reconcile a batch of parsed/observed facts into the attribute cloud
    (FR-LEARN-4, dark-engine audit #42).

    Auto-applies non-integral non-conflicting values, holds integral ones for the
    confirmation gate (FR-FB-3), surfaces conflicts without overwriting, and skips
    sensitive (EEO) fields (FR-ATTR-6). Every observation is caller-supplied,
    already-structured data (``{name, value, source?, is_integral?}``) — this
    endpoint does not itself run any free-text extraction.
    """
    observations = [o.model_dump() for o in body.observations]
    return feedback.ingest_parsed_input(
        campaign_id, observations  # type: ignore[arg-type]
    )
