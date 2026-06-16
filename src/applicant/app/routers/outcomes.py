"""Outcomes router (FR-LOG-4).

# STAGE B — Phase 1 wires one-tap mark-submitted (the manual outcome path); Phase 2
# adds auto-detection. Records an OutcomeEvent so learning sees conversions.
Gated behind the LLM-settings gate (FR-UI-5).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from applicant.app.container import Container
from applicant.app.deps import get_container, require_llm_configured
from applicant.core.entities.outcome_event import OutcomeEvent, OutcomeSource
from applicant.core.ids import OutcomeEventId, new_id

router = APIRouter(
    prefix="/api/outcomes", tags=["outcomes"], dependencies=[Depends(require_llm_configured)]
)


@router.get("")
def index() -> dict:
    return {"surface": "outcomes", "phase": 1, "status": "live"}


@router.post("/applications/{application_id}/mark-submitted", status_code=201)
def mark_submitted(application_id: str, container: Container = Depends(get_container)) -> dict:
    """One-tap mark-submitted when auto-detection cannot confirm (FR-LOG-4)."""
    event = OutcomeEvent(
        id=OutcomeEventId(new_id()),
        application_id=application_id,  # type: ignore[arg-type]
        type="submitted",
        source=OutcomeSource.MANUAL,
    )
    container.storage.outcomes.add(event)
    container.storage.commit()
    return {"outcome_id": event.id, "type": event.type, "source": event.source.value}
