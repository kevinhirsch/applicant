"""SetupWizard / OOBE driving port (FR-OOBE, FR-UI-5).

Sequenced UI setup: LLM gate first (FR-UI-5), then notification channels, fonts,
and the Workday-ready intake (FR-OOBE-2). Steps light up as backends land. The
LLM-settings gate blocks automated work until configured (409). Channel setup is a
gating step before automated work (FR-OOBE-3) — modeled here even though channel
backends arrive in Phase 1.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, runtime_checkable


class WizardStep(str, Enum):
    """Ordered OOBE steps (FR-OOBE-2)."""

    LLM = "llm"
    CHANNELS = "channels"
    FONTS = "fonts"
    ONBOARDING = "onboarding"


#: Canonical step order (FR-OOBE-2).
STEP_ORDER: tuple[WizardStep, ...] = (
    WizardStep.LLM,
    WizardStep.CHANNELS,
    WizardStep.FONTS,
    WizardStep.ONBOARDING,
)


@dataclass(frozen=True)
class LLMSettings:
    provider: str
    base_url: str
    api_key: str
    model: str
    context_window: int = 8192


@dataclass(frozen=True)
class TierSettings:
    """One ladder tier as set via the UI (FR-LLM-3)."""

    provider: str
    base_url: str
    model: str
    api_key: str = ""
    context_window: int = 8192


@dataclass(frozen=True)
class WizardStatus:
    llm_configured: bool
    channels_configured: bool
    fonts_ready: bool
    onboarding_complete: bool
    current_step: str = WizardStep.LLM.value
    steps_complete: list[str] = field(default_factory=list)


@runtime_checkable
class SetupWizardPort(Protocol):
    """Inbound port for the OOBE setup wizard."""

    def status(self) -> WizardStatus:
        """Return which wizard steps are complete (drives the gate)."""
        ...

    def configure_llm(self, settings: LLMSettings) -> None:
        """Persist LLM provider/model/endpoint/key (FR-LLM-2); ungates downstream."""
        ...

    def is_setup_gate_open(self) -> bool:
        """True once the LLM gate is satisfied (FR-UI-5)."""
        ...

    def advance_step(self, step: WizardStep) -> WizardStatus:
        """Mark a wizard step complete and return the new status (FR-OOBE-2)."""
        ...
