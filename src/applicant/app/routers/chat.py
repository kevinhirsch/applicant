"""Chat router (FR-CHAT-1).

# STAGE B — owned by Phase 4; flesh out here. Stub endpoints return placeholders.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from applicant.app.deps import require_llm_configured

router = APIRouter(prefix="/api/chat", tags=["chat"], dependencies=[Depends(require_llm_configured)])


@router.get("")
def index() -> dict:
    return {"surface": "chat", "status": "stage_b_stub", "phase": 4}
