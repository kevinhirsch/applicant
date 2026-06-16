"""Pending_actions router (FR-UI-3).

# STAGE B — owned by Phase 1; flesh out here. Stub endpoints return placeholders.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from applicant.app.deps import require_llm_configured

router = APIRouter(prefix="/api/pending-actions", tags=["pending_actions"], dependencies=[Depends(require_llm_configured)])


@router.get("")
def index() -> dict:
    return {"surface": "pending_actions", "status": "stage_b_stub", "phase": 1}
