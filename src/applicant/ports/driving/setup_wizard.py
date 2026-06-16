"""SetupWizard / OOBE driving port (FR-OOBE, FR-UI-5).

Sequenced UI setup: LLM gate first (FR-UI-5), then notification channels, fonts,
and the Workday-ready intake (FR-OOBE-2). Steps light up as backends land. The
LLM-settings gate blocks automated work until configured.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class LLMSettings:
    provider: str
    base_url: str
    api_key: str
    model: str


@dataclass(frozen=True)
class WizardStatus:
    llm_configured: bool
    channels_configured: bool
    fonts_ready: bool
    onboarding_complete: bool


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
