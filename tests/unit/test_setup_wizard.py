"""SetupService resumable wizard + tier-ladder persistence (FR-OOBE, FR-LLM-2/3)."""

from __future__ import annotations

import pytest

from applicant.adapters.storage.app_config_store import InMemoryAppConfigStore
from applicant.application.services.setup_service import SetupService
from applicant.ports.driving.setup_wizard import LLMSettings, TierSettings, WizardStep


def _svc(store=None, credentials=None) -> SetupService:
    return SetupService(config_store=store or InMemoryAppConfigStore(), credentials=credentials)


def test_gate_closed_until_llm_configured():
    svc = _svc()
    assert svc.is_setup_gate_open() is False
    svc.configure_llm(LLMSettings(provider="ollama", base_url="", api_key="", model="llama3.1"))
    assert svc.is_setup_gate_open() is True


def test_configure_llm_requires_provider_and_model():
    svc = _svc()
    with pytest.raises(ValueError):
        svc.configure_llm(LLMSettings(provider="", base_url="", api_key="", model="x"))


def test_wizard_state_persists_across_instances():
    store = InMemoryAppConfigStore()
    svc1 = _svc(store)
    svc1.configure_llm(LLMSettings(provider="ollama", base_url="", api_key="", model="llama3.1"))
    svc1.advance_step(WizardStep.CHANNELS)
    # New instance over the same store = simulated restart (FR-OOBE-1).
    svc2 = _svc(store)
    status = svc2.status()
    assert status.llm_configured is True
    assert status.channels_configured is True
    assert "llm" in status.steps_complete and "channels" in status.steps_complete


def test_current_step_advances_in_order():
    svc = _svc()
    assert svc.status().current_step == "llm"
    svc.configure_llm(LLMSettings(provider="ollama", base_url="", api_key="", model="m"))
    assert svc.status().current_step == "channels"
    svc.advance_step(WizardStep.CHANNELS)
    assert svc.status().current_step == "fonts"


def test_cannot_complete_llm_step_before_config():
    svc = _svc()
    with pytest.raises(ValueError):
        svc.advance_step(WizardStep.LLM)


def test_tier_ladder_set_reorder_and_build():
    svc = _svc()
    svc.set_tiers(
        [
            TierSettings(provider="ollama", base_url="http://localhost:11434", model="llama3.1", context_window=8192),
            TierSettings(provider="openrouter", base_url="https://openrouter.ai/api/v1", model="gpt-4o-mini", context_window=128000),
        ]
    )
    ladder = svc.build_ladder()
    assert ladder is not None and len(ladder) == 2
    assert ladder.at(0).model == "llama3.1"
    assert ladder.at(1).context_window == 128000


def test_set_tiers_min_one():
    svc = _svc()
    with pytest.raises(ValueError):
        svc.set_tiers([])


def test_get_tiers_omits_secrets():
    svc = _svc()
    svc.set_tiers(
        [TierSettings(provider="openrouter", base_url="https://openrouter.ai/api/v1", model="gpt-4o", api_key="sk-secret")]
    )
    tiers = svc.get_tiers()
    assert "api_key" not in tiers[0]
    assert all("secret" not in str(v) for v in tiers[0].values())


def test_secret_routed_through_credential_store(credential_store):
    svc = _svc(credentials=credential_store)
    svc.set_tiers(
        [TierSettings(provider="openrouter", base_url="https://openrouter.ai/api/v1", model="gpt-4o", api_key="sk-secret")]
    )
    # The plaintext key is NOT in the persisted config record...
    tiers = svc.get_tiers()
    assert "api_key" not in tiers[0]
    # ...but build_ladder resolves it from the credential store for actual calls.
    ladder = svc.build_ladder()
    assert ladder.at(0).api_key == "sk-secret"
