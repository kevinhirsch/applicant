"""Explain router — EXPLAIN backend endpoint (per-posting score breakdown).

Exposes the weighted greens/reds breakdown ``ExplainService`` computes + the
``ViabilityScored`` trigger (``app/lifespan.py``) durably caches on
``posting.rationale['breakdown']``. A GET here is a pure read of that cache
when present; on a miss (e.g. the posting predates this feature, or the
trigger hasn't fired yet) it lazily computes + caches one back so the surface
never 404s just because scoring beat this feature to a posting.

Backend only this round — no dedicated panel; reached via the a0 proxy
(``a0-applicant/api/explain.py``, auto-discovered by basename). Gated behind
the LLM gate like its digest/review siblings — even though the deterministic
factors work with no LLM at all, the posting itself only exists behind
onboarding/automated work.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from applicant.app.deps import get_explain_service, require_llm_configured
from applicant.core.ids import JobPostingId

router = APIRouter(
    prefix="/api/explain", tags=["explain"], dependencies=[Depends(require_llm_configured)]
)


@router.get("/{posting_id}")
def get_explanation(posting_id: str, explain=Depends(get_explain_service)) -> dict:
    """The full weighted greens/reds breakdown for one posting (EXPLAIN backend)."""
    breakdown = explain.explain_posting(JobPostingId(posting_id))  # type: ignore[arg-type]
    if breakdown is None:
        raise HTTPException(status_code=404, detail="posting not found")
    return explain.to_payload(breakdown)
