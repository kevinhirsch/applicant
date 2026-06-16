"""Setup / OOBE router — LLM-settings gate + tier ladder + wizard (FR-OOBE, FR-UI-5).

The FIRST UI deliverable: settings endpoints plus the gate. Posting valid LLM
settings opens the gate; gated routers depend on ``require_llm_configured``. All
setup is zero-CLI (NFR-ZEROCLI-1): provider/model/endpoint/key + the reorderable
tier ladder (FR-LLM-2/3) and per-step wizard advance (FR-OOBE-2) are all here.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from applicant.app.deps import get_setup_service
from applicant.ports.driving.setup_wizard import (
    LLMSettings,
    TierSettings,
    WizardStatus,
    WizardStep,
)

router = APIRouter(prefix="/api/setup", tags=["setup"])


class LLMSettingsIn(BaseModel):
    provider: str
    base_url: str = ""
    api_key: str = ""
    model: str
    context_window: int = 8192


class TierIn(BaseModel):
    provider: str
    base_url: str = ""
    model: str
    api_key: str = ""
    context_window: int = 8192


class LadderIn(BaseModel):
    tiers: list[TierIn] = Field(min_length=1)


def _status_dict(svc) -> dict:
    s: WizardStatus = svc.status()
    return {
        "llm_configured": s.llm_configured,
        "channels_configured": s.channels_configured,
        "fonts_ready": s.fonts_ready,
        "onboarding_complete": s.onboarding_complete,
        "current_step": s.current_step,
        "steps_complete": s.steps_complete,
        "gate_open": svc.is_setup_gate_open(),
    }


@router.get("/status")
def get_status(svc=Depends(get_setup_service)) -> dict:
    return _status_dict(svc)


@router.post("/llm", status_code=status.HTTP_204_NO_CONTENT)
def configure_llm(body: LLMSettingsIn, svc=Depends(get_setup_service)) -> None:
    try:
        svc.configure_llm(
            LLMSettings(
                provider=body.provider,
                base_url=body.base_url,
                api_key=body.api_key,
                model=body.model,
                context_window=body.context_window,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/llm/tiers")
def get_tiers(svc=Depends(get_setup_service)) -> dict:
    """Return the persisted tier ladder (secrets omitted) for the UI (FR-LLM-3)."""
    return {"tiers": svc.get_tiers()}


@router.put("/llm/tiers", status_code=status.HTTP_204_NO_CONTENT)
def set_tiers(body: LadderIn, svc=Depends(get_setup_service)) -> None:
    """Reorder / add / remove tiers (1-N, default 3 in the UI) (FR-LLM-3)."""
    try:
        svc.set_tiers(
            [
                TierSettings(
                    provider=t.provider,
                    base_url=t.base_url,
                    model=t.model,
                    api_key=t.api_key,
                    context_window=t.context_window,
                )
                for t in body.tiers
            ]
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/advance/{step}")
def advance_step(step: str, svc=Depends(get_setup_service)) -> dict:
    """Mark a wizard step complete and return the new status (FR-OOBE-2)."""
    try:
        wizard_step = WizardStep(step)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"unknown step: {step}"
        ) from exc
    try:
        svc.advance_step(wizard_step)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _status_dict(svc)
