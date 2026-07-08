"""Direct-URL intake router (P1-9 "save a job from any page").

One endpoint: paste (or bookmark) any posting URL and it enters the SAME
reviewed pipeline discovery results take — dedup, persist, viability scoring,
and a digest-approval pending item — tagged "added by you". Gated exactly like
the sibling discovery router (LLM + automated-work gates): capturing a role
kicks off scoring and the autonomous review pipeline, so it must not run before
onboarding completes.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from applicant.app.deps import (
    get_intake_service,
    require_automated_work,
    require_llm_configured,
)

router = APIRouter(
    prefix="/api/intake",
    tags=["intake"],
    dependencies=[Depends(require_llm_configured), Depends(require_automated_work)],
)


class SaveUrlIn(BaseModel):
    url: str


@router.post("/{campaign_id}/url")
def save_job_url(
    campaign_id: str, body: SaveUrlIn, svc=Depends(get_intake_service)
) -> dict:
    """Capture one posting URL into the campaign's pipeline (scored, tagged)."""
    return svc.save_url(campaign_id, body.url)  # type: ignore[arg-type]
