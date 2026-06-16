"""Outcomes router (FR-LOG-4).

# STAGE B — owned by Phase 2; flesh out here. Stub endpoints return placeholders.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from applicant.app.deps import require_llm_configured

router = APIRouter(prefix="/api/outcomes", tags=["outcomes"], dependencies=[Depends(require_llm_configured)])


@router.get("")
def index() -> dict:
    return {"surface": "outcomes", "status": "stage_b_stub", "phase": 2}
