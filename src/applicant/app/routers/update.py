"""Update router (FR-OOBE-4, FR-INSTALL-2).

# STAGE B — owned by Phase 4; flesh out here. Stub endpoints return placeholders.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from applicant.app.deps import require_llm_configured

router = APIRouter(prefix="/api/update", tags=["update"], dependencies=[Depends(require_llm_configured)])


@router.get("")
def index() -> dict:
    return {"surface": "update", "status": "stage_b_stub", "phase": 4}
