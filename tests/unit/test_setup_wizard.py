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


def test_set_tiers_preserves_key_by_ref_on_edit(credential_store):
    """FR-LLM-3 editor: editing a tier without re-typing its key keeps the key.

    The UI gets back ``api_key_ref`` (a non-secret marker) from get_tiers and sends
    it back with a blank api_key; set_tiers re-seals the existing secret."""
    svc = _svc(credentials=credential_store)
    svc.set_tiers(
        [TierSettings(provider="openrouter", base_url="https://openrouter.ai/api/v1", model="gpt-4o", api_key="sk-keep")]
    )
    ref = svc.get_tiers()[0].get("api_key_ref")
    assert ref  # a marker is exposed, not the secret
    # Edit the model only; carry the ref, leave api_key blank.
    svc.set_tiers(
        [TierSettings(provider="openrouter", base_url="https://openrouter.ai/api/v1", model="gpt-4o-mini", api_key="", api_key_ref=ref)]
    )
    ladder = svc.build_ladder()
    assert ladder.at(0).model == "gpt-4o-mini"
    assert ladder.at(0).api_key == "sk-keep"  # key survived the edit


def test_set_tiers_preserves_keys_across_reorder(credential_store):
    """Reordering two keyed tiers keeps EACH tier's own key (two-phase re-seal)."""
    svc = _svc(credentials=credential_store)
    svc.set_tiers([
        TierSettings(provider="openai", base_url="https://a.test/v1", model="m-a", api_key="key-A"),
        TierSettings(provider="openai", base_url="https://b.test/v1", model="m-b", api_key="key-B"),
    ])
    got = svc.get_tiers()
    ref_a, ref_b = got[0]["api_key_ref"], got[1]["api_key_ref"]
    # Swap their order, carrying each tier's ref, no re-typed keys.
    svc.set_tiers([
        TierSettings(provider="openai", base_url="https://b.test/v1", model="m-b", api_key="", api_key_ref=ref_b),
        TierSettings(provider="openai", base_url="https://a.test/v1", model="m-a", api_key="", api_key_ref=ref_a),
    ])
    ladder = svc.build_ladder()
    assert (ladder.at(0).model, ladder.at(0).api_key) == ("m-b", "key-B")
    assert (ladder.at(1).model, ladder.at(1).api_key) == ("m-a", "key-A")


# === FR-NOTIF-5: quiet-hours persistence ====================================
def test_quiet_hours_default_is_24_7():
    svc = _svc()
    qh = svc.get_quiet_hours()
    assert qh["enabled"] is False  # 24/7 by default — nothing is deferred
    assert qh["start"] == "22:00" and qh["end"] == "07:00"


def test_quiet_hours_persist_across_instances():
    store = InMemoryAppConfigStore()
    svc1 = _svc(store)
    svc1.set_quiet_hours(enabled=True, start="22:30", end="7:15", tz="America/Phoenix")
    # New instance over the same store = simulated restart (FR-OOBE-1).
    qh = _svc(store).get_quiet_hours()
    assert qh["enabled"] is True
    assert qh["start"] == "22:30" and qh["end"] == "07:15"  # zero-padded
    assert qh["tz"] == "America/Phoenix"


def test_quiet_hours_alongside_channels():
    # Saving quiet hours must not clobber existing channel config (same record).
    store = InMemoryAppConfigStore()
    svc = _svc(store)
    svc.configure_channels(discord_webhook_url="https://discord.com/api/webhooks/x")
    svc.set_quiet_hours(enabled=True, start="23:00", end="06:00")
    assert svc.channels_configured() is True
    assert svc.get_quiet_hours()["enabled"] is True


def test_quiet_hours_rejects_bad_time():
    svc = _svc()
    with pytest.raises(ValueError):
        svc.set_quiet_hours(enabled=True, start="25:00", end="07:00")
    with pytest.raises(ValueError):
        svc.set_quiet_hours(enabled=True, start="10pm", end="07:00")


def test_quiet_hours_disable_is_24_7():
    svc = _svc()
    svc.set_quiet_hours(enabled=True, start="22:00", end="07:00")
    svc.set_quiet_hours(enabled=False)
    assert svc.get_quiet_hours()["enabled"] is False
