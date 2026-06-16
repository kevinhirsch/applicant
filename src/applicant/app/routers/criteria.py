"""Criteria router (FR-CRIT-1/2/3). Gated behind the LLM-settings gate (FR-UI-5).

Exposes per-campaign criteria get/edit. Criteria are human-readable + editable at all
times (FR-CRIT-2); integral changes route through the confirmation gate (FR-FB-3) ->
HTTP 409. Learned adjustments are surfaced in the response and user-overridable
(``clear_learned``), so LLM/learning mutations are always transparent (FR-CRIT-3).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from applicant.app.deps import get_criteria_service, require_llm_configured
from applicant.core.entities.search_criteria import SearchCriteria
from applicant.core.errors import ConfirmationRequired

router = APIRouter(
    prefix="/api/criteria", tags=["criteria"], dependencies=[Depends(require_llm_configured)]
)


class EditCriteriaIn(BaseModel):
    titles: list[str] | None = None
    locations: list[str] | None = None
    work_modes: list[str] | None = None
    keywords: list[str] | None = None
    salary_floor: int | None = None
    human_readable: str | None = None
    confirm: bool = False
    clear_learned: bool = False


class LearnedAdjustmentIn(BaseModel):
    adjustment: dict
    rationale: str = ""


def _to_dict(c: SearchCriteria) -> dict:
    return {
        "campaign_id": c.campaign_id,
        "human_readable": c.human_readable,
        "titles": list(c.titles),
        "locations": list(c.locations),
        "work_modes": list(c.work_modes),
        "salary_floor": c.salary_floor,
        "keywords": list(c.keywords),
        "learned_adjustments": c.learned_adjustments,
    }


@router.get("/{campaign_id}")
def get_criteria(campaign_id: str, svc=Depends(get_criteria_service)) -> dict:
    return _to_dict(svc.get_criteria(campaign_id))  # type: ignore[arg-type]


@router.put("/{campaign_id}")
def edit_criteria(
    campaign_id: str, body: EditCriteriaIn, svc=Depends(get_criteria_service)
) -> dict:
    changes = body.model_dump(exclude_none=True, exclude={"confirm", "clear_learned"})
    try:
        updated = svc.edit_criteria(
            campaign_id,  # type: ignore[arg-type]
            changes=changes,
            confirm=body.confirm,
            clear_learned=body.clear_learned,
        )
    except ConfirmationRequired as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _to_dict(updated)


@router.post("/{campaign_id}/learned")
def apply_learned(
    campaign_id: str, body: LearnedAdjustmentIn, svc=Depends(get_criteria_service)
) -> dict:
    updated = svc.apply_learned_adjustment(
        campaign_id,  # type: ignore[arg-type]
        adjustment=body.adjustment,
        rationale=body.rationale,
    )
    return _to_dict(updated)
