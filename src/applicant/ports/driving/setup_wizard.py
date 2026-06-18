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
    SANDBOX = "sandbox"  # native Proxmox Windows VM connection/login (FR-OOBE)
    FONTS = "fonts"
    ONBOARDING = "onboarding"


#: Canonical step order (FR-OOBE-2). The sandbox-connection step sits after channels
#: and before fonts; it only GATES when the proxmox-windows backend is selected.
STEP_ORDER: tuple[WizardStep, ...] = (
    WizardStep.LLM,
    WizardStep.CHANNELS,
    WizardStep.SANDBOX,
    WizardStep.FONTS,
    WizardStep.ONBOARDING,
)


@dataclass(frozen=True)
class SandboxConnectionSettings:
    """Native Proxmox Windows VM connection + login data, collected in the UI (FR-OOBE).

    Non-secrets (API URL/node/VMID/CDP/method/RDP user) persist to app-config; the
    SECRETS (Proxmox API token secret + RDP password) are sealed in the credential
    vault and NEVER logged or returned (FR-VAULT-3, NFR-PRIV-1).
    """

    proxmox_api_url: str
    proxmox_node: str
    proxmox_token_id: str
    proxmox_token_secret: str  # SECRET -> vault
    template_vmid: int
    clone_mode: str = "snapshot-revert"
    cdp_host: str = ""
    cdp_port: int = 9222
    rdp_username: str = ""
    rdp_password: str = ""  # SECRET -> vault
    takeover_method: str = "rdp"
    takeover_url_template: str = ""


@dataclass(frozen=True)
class LLMSettings:
    provider: str
    base_url: str
    api_key: str
    model: str
    context_window: int = 8192


@dataclass(frozen=True)
class TierSettings:
    """One ladder tier as set via the UI (FR-LLM-3).

    ``api_key_ref`` lets the editor preserve an already-sealed key across an
    edit/reorder without re-typing it: the UI sends back the ref it received from
    ``get_tiers`` and leaves ``api_key`` blank, and ``set_tiers`` re-seals the
    existing secret at the tier's new position (see SetupService.set_tiers).
    """

    provider: str
    base_url: str
    model: str
    api_key: str = ""
    api_key_ref: str = ""
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
