"""Feedback router (FR-FB-1/2/3).

Free-text/chat feedback at any time and a guided survey, both feeding per-campaign
learning (FR-FB-2, FR-LEARN-3). Survey answers cross-reference the attribute cloud,
honoring the confirmation gate for integral changes (FR-FB-3).

``GET /{campaign_id}`` is the read side of what was otherwise a write-only surface
(dark-engine audit item 23): the user could tell the assistant things (decline
reasons, résumé/answer revision instructions) but never see what actually stuck.
It reuses ``FeedbackSummaryProvider`` — already walking per-application feedback to
feed the curation nudge (FR-MIND-1/-7/-13, FR-LEARN-3) — as a read-model instead of
re-deriving the same walk.

Gated behind the LLM gate (FR-UI-5).
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from applicant.app.deps import get_feedback_service, get_storage, require_llm_configured
from applicant.application.services.feedback_history import FeedbackSummaryProvider

router = APIRouter(
    prefix="/api/feedback", tags=["feedback"], dependencies=[Depends(require_llm_configured)]
)

#: Cap on how much feedback history one read returns. Generous relative to the
#: curation nudge's own ``DEFAULT_MAX_SUMMARIES`` (25) since this answers a direct
#: "what have I told it" read for ONE campaign rather than feeding a cheap scheduled
#: tick across every campaign — still bounded (pure storage reads, no LLM/network),
#: so the read stays cheap.
MAX_FEEDBACK_HISTORY = 200


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


@router.get("/{campaign_id}")
def feedback_history(campaign_id: str, storage=Depends(get_storage)) -> dict:
    """Everything the user has told the assistant for one campaign, read back
    (dark-engine audit item 23).

    Maps each stored feedback item (digest decline-with-feedback, FR-DIG-5; résumé/
    answer revision instructions, FR-RESUME-8) through the SAME
    :class:`FeedbackSummaryProvider` walk the curation nudge already uses, so this is
    a pure read over existing storage — no new persistence, no LLM call. Filtered to
    ``campaign_id`` so a caller only ever sees its own campaign's history.
    """
    provider = FeedbackSummaryProvider(max_summaries=MAX_FEEDBACK_HISTORY)
    summaries = provider(storage, datetime.now(UTC))
    items = [
        {
            "run_id": s.run_id,
            "text": s.text,
            "topic": s.topic,
            # The provider only ever tags two kinds of feedback (see module
            # docstring); the run_id prefix it assigns each is a stable, cheap way
            # to tell them apart without threading a new field through RunSummary.
            "kind": "decline" if s.run_id.startswith("feedback-decline-") else "revision",
        }
        for s in summaries
        if s.campaign_id == campaign_id
    ]
    return {"campaign_id": campaign_id, "items": items}
