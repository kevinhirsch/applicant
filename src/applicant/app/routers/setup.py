"""Setup / OOBE router — the LLM-settings gate (FR-OOBE, FR-UI-5).

This is the FIRST UI deliverable: a settings endpoint plus the gate. Posting valid
LLM settings opens the gate; gated routers depend on ``require_llm_configured``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from applicant.app.deps import get_setup_service
from applicant.ports.driving.setup_wizard import LLMSettings

router = APIRouter(prefix="/api/setup", tags=["setup"])


class LLMSettingsIn(BaseModel):
    provider: str
    base_url: str = ""
    api_key: str = ""
    model: str


@router.get("/status")
def get_status(svc=Depends(get_setup_service)) -> dict:
    s = svc.status()
    return {
        "llm_configured": s.llm_configured,
        "channels_configured": s.channels_configured,
        "fonts_ready": s.fonts_ready,
        "onboarding_complete": s.onboarding_complete,
        "gate_open": svc.is_setup_gate_open(),
    }


@router.post("/llm", status_code=status.HTTP_204_NO_CONTENT)
def configure_llm(body: LLMSettingsIn, svc=Depends(get_setup_service)) -> None:
    try:
        svc.configure_llm(
            LLMSettings(
                provider=body.provider,
                base_url=body.base_url,
                api_key=body.api_key,
                model=body.model,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
