"""Criteria router (FR-CRIT-1/2/3). Gated behind the LLM-settings gate (FR-UI-5).

Exposes per-campaign criteria get/edit. Criteria are human-readable + editable at all
times (FR-CRIT-2); integral changes route through the confirmation gate (FR-FB-3) ->
HTTP 409. Learned adjustments are surfaced in the response and user-overridable
(``clear_learned``), so LLM/learning mutations are always transparent (FR-CRIT-3).
"""

from __future__ import annotations

import dataclasses

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from applicant.app.container import Container
from applicant.app.deps import (
    get_container,
    get_criteria_service,
    get_storage,
    require_llm_configured,
)
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


class ExplorationBudgetIn(BaseModel):
    exploration_budget: float


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


# === Learned converting-role signature + exploration budget (FR-LEARN-5/6) ===
# Surfaces what the engine has *learned* converts (the converting-role signature,
# grouped by facet) and the exploration budget knob, so the front-door can show
# the learned bias transparently and let the user steer the explore/exploit mix.
# Co-located here because the criteria surface is "what roles the engine targets"
# and these are the learned, user-overridable side of the same picture.
@router.get("/{campaign_id}/signature")
def converting_signature(
    campaign_id: str, container: Container = Depends(get_container)
) -> dict:
    """The learned converting-role signature + the exploration budget knob.

    ``signature`` is a per-facet (role/seniority/skill/work_mode/comp/source/
    variant) digest of what actually converts, ordered by learned weight — a
    transparent, user-overridable view of the learned bias. ``samples`` is how
    many converting applications it was learned from; ``exploration_budget`` is the
    fraction of effort reserved for under-sampled/new sources.
    """
    model = container.learning_service.load_model(campaign_id)  # type: ignore[arg-type]
    summary = container.advanced_learning_service.converting_signature_summary(model)
    return {
        "campaign_id": campaign_id,
        "signature": summary,
        "samples": getattr(model, "converting_samples", 0),
        "exploration_budget": getattr(model, "exploration_budget", None),
    }


@router.get("/{campaign_id}/alignment/{posting_id}")
def posting_alignment(
    campaign_id: str,
    posting_id: str,
    container: Container = Depends(get_container),
    storage=Depends(get_storage),
) -> dict:
    """WHY a posting aligns with what has actually converted before (dark-engine
    audit #39, "match to your past wins").

    Cheap, deterministic, no-LLM lexical alignment (FR-LEARN-5) of the posting's
    title/description against the SAME discrete converting-role signature that
    already biases scoring behind the scenes (``ScoringService._signature_alignment``
    -> ``AdvancedLearningService.text_alignment``) — this is a READ-ONLY companion
    that explains the number (which facet/value pairs from your past wins actually
    show up in this posting) rather than re-folding or double-counting a signal.
    ``cold_start`` is True when nothing has converted yet, so the caller can render
    "not enough data yet" instead of a misleading 0%. 404 when the posting does not
    exist or belongs to a different campaign.
    """
    posting = storage.postings.get(posting_id)  # type: ignore[arg-type]
    if posting is None or str(posting.campaign_id) != str(campaign_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such posting.")
    model = container.learning_service.load_model(campaign_id)  # type: ignore[arg-type]
    text = f"{posting.title or ''} {posting.description or ''}".strip()
    result = container.advanced_learning_service.explain_text_alignment(model, text)
    return {"campaign_id": campaign_id, "posting_id": posting_id, **result}


@router.put("/{campaign_id}/exploration-budget")
def set_exploration_budget(
    campaign_id: str, body: ExplorationBudgetIn, container: Container = Depends(get_container)
) -> dict:
    """Set the exploration budget (0.0–1.0) — the explore/exploit mix (FR-LEARN-6)."""
    if not (0.0 <= body.exploration_budget <= 1.0):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Exploration budget must be between 0 and 1.",
        )
    ls = container.learning_service
    model = ls.load_model(campaign_id)  # type: ignore[arg-type]
    ls.persist_model(dataclasses.replace(model, exploration_budget=body.exploration_budget))
    return {"campaign_id": campaign_id, "exploration_budget": body.exploration_budget}
