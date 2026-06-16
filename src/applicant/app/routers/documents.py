"""Documents router (FR-RESUME-8, FR-ANSWER-1).

# STAGE B — owned by Phase 3; flesh out here. Stub endpoints return placeholders.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from applicant.app.deps import require_llm_configured

router = APIRouter(prefix="/api/documents", tags=["documents"], dependencies=[Depends(require_llm_configured)])


@router.get("")
def index() -> dict:
    return {"surface": "documents", "status": "stage_b_stub", "phase": 3}
