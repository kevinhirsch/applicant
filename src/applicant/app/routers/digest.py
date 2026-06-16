"""Digest router (FR-DIG, FR-FB-1).

# STAGE B — owned by Phase 1; flesh out here. Stub endpoints return placeholders.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from applicant.app.deps import require_llm_configured

router = APIRouter(prefix="/api/digest", tags=["digest"], dependencies=[Depends(require_llm_configured)])


@router.get("")
def index() -> dict:
    return {"surface": "digest", "status": "stage_b_stub", "phase": 1}
