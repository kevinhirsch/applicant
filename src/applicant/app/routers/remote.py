"""Remote router (FR-SANDBOX-3, FR-PREFILL-5).

# STAGE B — owned by Phase 2; flesh out here. Stub endpoints return placeholders.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from applicant.app.deps import require_llm_configured

router = APIRouter(prefix="/api/remote", tags=["remote"], dependencies=[Depends(require_llm_configured)])


@router.get("")
def index() -> dict:
    return {"surface": "remote", "status": "stage_b_stub", "phase": 2}
