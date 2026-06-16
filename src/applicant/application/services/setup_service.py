"""SetupService — OOBE wizard + LLM gate (FR-OOBE, FR-UI-5). Real-ish.

Tracks LLM configuration and exposes the gate state the routers use to block
downstream routes with 409 until the LLM is configured.
"""

from __future__ import annotations

from applicant.ports.driving.setup_wizard import LLMSettings, WizardStatus


class SetupService:
    """Implements the SetupWizard driving port."""

    def __init__(self, *, llm_configured: bool = False) -> None:
        self._llm: LLMSettings | None = None
        self._llm_preconfigured = llm_configured
        self._channels_configured = False
        self._fonts_ready = False
        self._onboarding_complete = False

    def status(self) -> WizardStatus:
        return WizardStatus(
            llm_configured=self.is_setup_gate_open(),
            channels_configured=self._channels_configured,
            fonts_ready=self._fonts_ready,
            onboarding_complete=self._onboarding_complete,
        )

    def configure_llm(self, settings: LLMSettings) -> None:
        if not settings.provider or not settings.model:
            raise ValueError("LLM provider and model are required (FR-LLM-2).")
        self._llm = settings

    def is_setup_gate_open(self) -> bool:
        """True once the LLM gate is satisfied (FR-UI-5)."""
        return self._llm is not None or self._llm_preconfigured
