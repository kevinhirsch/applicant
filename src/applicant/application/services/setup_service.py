"""SetupService — OOBE resumable wizard + LLM gate (FR-OOBE, FR-LLM-2/3, FR-UI-5).

A real, resumable wizard: it persists the LLM tier ladder and per-step completion
to an :class:`AppConfigStore` so the wizard survives restarts (FR-OOBE-1). The
LLM-settings gate stays first and blocks downstream routes (409) until satisfied
(FR-UI-5). Channel setup is modeled as a gating step (FR-OOBE-3) even though the
channel backends arrive in Phase 1.

Secrets (api keys) are routed through the encrypted credential store; only a
non-secret marker is persisted in app-config, so keys never reach the logs or the
plaintext config table (FR-VAULT-3, NFR-PRIV-1).
"""

from __future__ import annotations

from typing import Any

from applicant.adapters.storage.app_config_store import (
    AppConfigStore,
    InMemoryAppConfigStore,
)
from applicant.observability.logging import get_logger
from applicant.ports.driven.llm import TierConfig, TierLadder
from applicant.ports.driving.setup_wizard import (
    STEP_ORDER,
    LLMSettings,
    TierSettings,
    WizardStatus,
    WizardStep,
)

log = get_logger(__name__)

_LADDER_KEY = "llm.tier_ladder"
_STEPS_KEY = "wizard.steps_complete"
_DEFAULT_MAX_TIERS = 10


class SetupService:
    """Implements the SetupWizard driving port with persistent state."""

    def __init__(
        self,
        *,
        llm_configured: bool = False,
        config_store: AppConfigStore | None = None,
        credentials: Any | None = None,
    ) -> None:
        self._store = config_store or InMemoryAppConfigStore()
        self._credentials = credentials
        self._llm_preconfigured = llm_configured
        self._fonts_ready = False
        self._onboarding_complete = False

    # --- persistence helpers ---------------------------------------------
    def _load_tiers(self) -> list[dict[str, Any]]:
        rec = self._store.get(_LADDER_KEY)
        if not rec:
            return []
        return list(rec.get("tiers", []))

    def _save_tiers(self, tiers: list[dict[str, Any]]) -> None:
        self._store.set(_LADDER_KEY, {"tiers": tiers})

    def _steps_complete(self) -> set[str]:
        rec = self._store.get(_STEPS_KEY)
        steps = set(rec.get("steps", [])) if rec else set()
        if self._fonts_ready:
            steps.add(WizardStep.FONTS.value)
        if self._onboarding_complete:
            steps.add(WizardStep.ONBOARDING.value)
        return steps

    # --- status ----------------------------------------------------------
    def status(self) -> WizardStatus:
        steps = self._steps_complete()
        if self.is_setup_gate_open():
            steps.add(WizardStep.LLM.value)
        ordered = [s.value for s in STEP_ORDER if s.value in steps]
        current = next((s.value for s in STEP_ORDER if s.value not in steps), STEP_ORDER[-1].value)
        return WizardStatus(
            llm_configured=self.is_setup_gate_open(),
            channels_configured=WizardStep.CHANNELS.value in steps,
            fonts_ready=WizardStep.FONTS.value in steps,
            onboarding_complete=WizardStep.ONBOARDING.value in steps,
            current_step=current,
            steps_complete=ordered,
        )

    # --- LLM settings / tier ladder (FR-LLM-2/3) -------------------------
    def configure_llm(self, settings: LLMSettings) -> None:
        """Set the L1 tier (creates or replaces the first ladder rung)."""
        if not settings.provider or not settings.model:
            raise ValueError("LLM provider and model are required (FR-LLM-2).")
        tier = self._tier_to_record(
            TierSettings(
                provider=settings.provider,
                base_url=settings.base_url,
                model=settings.model,
                api_key=settings.api_key,
                context_window=settings.context_window,
            ),
            tier_no=1,
        )
        tiers = self._load_tiers()
        if tiers:
            tiers[0] = tier
        else:
            tiers = [tier]
        self._save_tiers(tiers)
        log.info("llm_configured", provider=settings.provider, model=settings.model)

    def get_tiers(self) -> list[dict[str, Any]]:
        """Return the persisted ladder as non-secret records (for the UI)."""
        return [{k: v for k, v in t.items() if k != "api_key"} for t in self._load_tiers()]

    def set_tiers(self, tiers: list[TierSettings]) -> None:
        """Replace the whole ladder (reorder/add/remove; 1-N, FR-LLM-3)."""
        if not tiers:
            raise ValueError("At least one tier is required (FR-LLM-3).")
        if len(tiers) > _DEFAULT_MAX_TIERS:
            raise ValueError(f"At most {_DEFAULT_MAX_TIERS} tiers are supported.")
        records = [self._tier_to_record(t, i + 1) for i, t in enumerate(tiers)]
        for r in records:
            if not r["provider"] or not r["model"]:
                raise ValueError("Each tier needs provider and model (FR-LLM-3).")
        self._save_tiers(records)
        log.info("llm_ladder_set", tiers=len(records))

    def build_ladder(self) -> TierLadder | None:
        """Materialize a :class:`TierLadder` from persisted config (with secrets)."""
        tiers = self._load_tiers()
        if not tiers:
            return None
        configs = [
            TierConfig(
                provider=t["provider"],
                base_url=t.get("base_url", ""),
                model=t["model"],
                api_key=self._resolve_secret(t),
                context_window=int(t.get("context_window", 8192)),
            )
            for t in tiers
        ]
        return TierLadder(tiers=configs)

    def _tier_to_record(self, tier: TierSettings, tier_no: int) -> dict[str, Any]:
        record: dict[str, Any] = {
            "provider": tier.provider,
            "base_url": tier.base_url,
            "model": tier.model,
            "context_window": tier.context_window,
        }
        if tier.api_key:
            if self._credentials is not None:
                # Seal the key in the credential store; persist only a marker.
                self._store_secret(f"llm.tier{tier_no}", tier.api_key)
                record["api_key_ref"] = f"llm.tier{tier_no}"
            else:
                # No credential store wired (tests): keep inline but never logged.
                record["api_key"] = tier.api_key
        return record

    def _resolve_secret(self, record: dict[str, Any]) -> str:
        if "api_key" in record:
            return record["api_key"]
        ref = record.get("api_key_ref")
        if ref and self._credentials is not None:
            cred = self._retrieve_secret(ref)
            return cred or ""
        return ""

    # --- credential-store helpers (LLM keys reuse the vault path) ---------
    def _store_secret(self, ref: str, secret: str) -> None:
        from applicant.core.ids import CampaignId
        from applicant.ports.driven.credential_store import Credential

        self._credentials.store(
            CampaignId("__system__"),
            Credential(tenant_key=ref, username="api_key", secret=secret),
        )

    def _retrieve_secret(self, ref: str) -> str | None:
        from applicant.core.ids import CampaignId

        cred = self._credentials.retrieve(CampaignId("__system__"), ref)
        return cred.secret if cred else None

    # --- gate + step advance ---------------------------------------------
    def is_setup_gate_open(self) -> bool:
        """True once the LLM gate is satisfied (FR-UI-5)."""
        return bool(self._load_tiers()) or self._llm_preconfigured

    def advance_step(self, step: WizardStep) -> WizardStatus:
        """Mark a wizard step complete (FR-OOBE-2). LLM is gated by its config."""
        if step is WizardStep.LLM and not self.is_setup_gate_open():
            raise ValueError("Configure the LLM before completing the LLM step (FR-UI-5).")
        if step is WizardStep.FONTS:
            self._fonts_ready = True
        elif step is WizardStep.ONBOARDING:
            self._onboarding_complete = True
        rec = self._store.get(_STEPS_KEY) or {"steps": []}
        steps = set(rec.get("steps", []))
        steps.add(step.value)
        self._store.set(_STEPS_KEY, {"steps": sorted(steps)})
        log.info("wizard_step_complete", step=step.value)
        return self.status()
