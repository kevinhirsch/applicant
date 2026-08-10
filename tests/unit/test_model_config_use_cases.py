"""EPIC MODEL-CONFIG — per-use-case model/endpoint bindings on SetupService.

These lock the MODEL-CONFIG contract (docs/APPLICANT-BACKLOG.md §EPIC MODEL-CONFIG)
at the service layer, REUSING the existing tier ladder + ``ModelEndpointService``
registry (no parallel config system, no forked ladder):

  * fresh install = zero config: no bindings stored, every use case resolves to the
    shared ``build_ladder()`` so the app works out of the box;
  * binding a use case to a saved endpoint PREPENDS it as the primary tier and keeps
    the full ladder below it as the fallback;
  * validation (unknown use case / unknown endpoint / missing model);
  * verified local-only private mode drops a bound cloud endpoint, same as any tier;
  * the smart-routing master-flag override round-trips.

Hermetic: the model-endpoint live probe is disabled (``probe=False``) so nothing
touches the network; both services share one in-memory config store + the real
credential vault, exactly like production.
"""

from __future__ import annotations

import pytest

from applicant.adapters.storage.app_config_store import InMemoryAppConfigStore
from applicant.application.services.model_endpoint_service import ModelEndpointService
from applicant.application.services.setup_service import SetupService
from applicant.core.errors import InvalidInput
from applicant.ports.driving.setup_wizard import TierSettings


def _stack(store=None, credentials=None, *, local_only=False):
    """A SetupService + ModelEndpointService sharing one store (as in production)."""
    store = store or InMemoryAppConfigStore()
    setup = SetupService(
        config_store=store, credentials=credentials, local_only=local_only
    )
    endpoints = ModelEndpointService(config_store=store, credentials=credentials)
    return setup, endpoints


def _resolver(endpoints: ModelEndpointService):
    """Mirror the setup router's endpoint_resolver: resolve the sealed key too."""

    def _resolve(endpoint_id: str):
        rec = endpoints.get_endpoint(endpoint_id)
        if rec is None:
            return None
        return {
            "base_url": rec.get("base_url", ""),
            "api_key": endpoints._resolve_key(rec),
            "name": rec.get("name", ""),
        }

    return _resolve


def _seed_ladder(setup: SetupService):
    setup.set_tiers(
        [
            TierSettings(
                provider="ollama",
                base_url="http://localhost:11434",
                model="qwen-local",
                context_window=8192,
            ),
            TierSettings(
                provider="openai",
                base_url="https://api.deepseek.com/v1",
                model="deepseek-fallback",
                api_key="sk-fallback",
                context_window=64000,
            ),
        ]
    )


# === fresh install / zero config ==========================================
def test_fresh_install_has_no_bindings():
    setup, _ = _stack()
    assert setup.get_use_case_bindings() == {}
    assert setup.get_use_case_binding("scoring") is None


def test_unbound_use_case_resolves_to_shared_ladder():
    setup, endpoints = _stack()
    _seed_ladder(setup)
    ladder = setup.resolve_use_case_ladder("scoring", endpoint_resolver=_resolver(endpoints))
    # Identical to the shared ladder — nothing forked, nothing prepended.
    assert ladder is not None
    assert [t.model for t in ladder.tiers] == ["qwen-local", "deepseek-fallback"]


def test_resolve_without_resolver_is_the_base_ladder_even_if_bound():
    setup, endpoints = _stack()
    _seed_ladder(setup)
    eid = endpoints.add_endpoint(
        base_url="https://api.deepseek.com/v1", name="DeepSeek", probe=False
    )["id"]
    setup.set_use_case_binding(
        "drafting_cover_letter", mode="endpoint", endpoint_id=eid, model="deepseek-v4-flash"
    )
    # No resolver wired -> cannot resolve the sealed key, so fall back safely.
    ladder = setup.resolve_use_case_ladder("drafting_cover_letter")
    assert [t.model for t in ladder.tiers] == ["qwen-local", "deepseek-fallback"]


# === binding a use case to a saved endpoint ================================
def test_bound_endpoint_is_prepended_and_ladder_kept_as_fallback():
    setup, endpoints = _stack()
    _seed_ladder(setup)
    eid = endpoints.add_endpoint(
        base_url="https://openrouter.ai/api/v1", name="OpenRouter", probe=False
    )["id"]
    setup.set_use_case_binding(
        "drafting_cover_letter", mode="endpoint", endpoint_id=eid, model="deepseek-v4-flash"
    )
    ladder = setup.resolve_use_case_ladder(
        "drafting_cover_letter", endpoint_resolver=_resolver(endpoints)
    )
    # Primary is the bound endpoint/model; the whole shared ladder remains below it.
    assert [t.model for t in ladder.tiers] == [
        "deepseek-v4-flash",
        "qwen-local",
        "deepseek-fallback",
    ]
    assert ladder.tiers[0].base_url == "https://openrouter.ai/api/v1"
    assert ladder.tiers[0].provider == "openai"


def test_bound_endpoint_provider_detects_ollama():
    setup, endpoints = _stack()
    _seed_ladder(setup)
    eid = endpoints.add_endpoint(
        base_url="http://localhost:11434", name="Local", probe=False
    )["id"]
    setup.set_use_case_binding("chat", mode="endpoint", endpoint_id=eid, model="qwen3")
    ladder = setup.resolve_use_case_ladder("chat", endpoint_resolver=_resolver(endpoints))
    assert ladder.tiers[0].provider == "ollama"
    assert ladder.tiers[0].model == "qwen3"


def test_bound_endpoint_sealed_key_resolves_through_the_vault(credential_store):
    store = InMemoryAppConfigStore()
    setup, endpoints = _stack(store=store, credentials=credential_store)
    _seed_ladder(setup)
    eid = endpoints.add_endpoint(
        base_url="https://openrouter.ai/api/v1",
        api_key="sk-secret-key",
        name="OpenRouter",
        probe=False,
    )["id"]
    setup.set_use_case_binding(
        "research", mode="endpoint", endpoint_id=eid, model="some-model"
    )
    ladder = setup.resolve_use_case_ladder("research", endpoint_resolver=_resolver(endpoints))
    # The plaintext key is not in the endpoint record...
    assert "api_key" not in (endpoints.get_endpoint(eid) or {})
    # ...but it is resolved from the shared vault into the primary tier for real calls.
    assert ladder.tiers[0].api_key == "sk-secret-key"


# === clearing / defaulting ================================================
def test_clear_binding_resets_to_default():
    setup, endpoints = _stack()
    _seed_ladder(setup)
    eid = endpoints.add_endpoint(
        base_url="https://openrouter.ai/api/v1", probe=False
    )["id"]
    setup.set_use_case_binding("scoring", mode="endpoint", endpoint_id=eid, model="m")
    assert setup.get_use_case_binding("scoring") is not None
    setup.clear_use_case_binding("scoring")
    assert setup.get_use_case_binding("scoring") is None
    ladder = setup.resolve_use_case_ladder("scoring", endpoint_resolver=_resolver(endpoints))
    assert [t.model for t in ladder.tiers] == ["qwen-local", "deepseek-fallback"]


def test_mode_default_clears_any_existing_override():
    setup, endpoints = _stack()
    eid = endpoints.add_endpoint(base_url="https://x.ai/v1", probe=False)["id"]
    setup.set_use_case_binding("chat", mode="endpoint", endpoint_id=eid, model="m")
    setup.set_use_case_binding("chat", mode="default")
    assert setup.get_use_case_bindings() == {}


# === validation ============================================================
def test_unknown_use_case_rejected():
    setup, _ = _stack()
    with pytest.raises(InvalidInput):
        setup.set_use_case_binding("not_a_use_case", mode="default")


def test_unknown_mode_rejected():
    setup, _ = _stack()
    with pytest.raises(InvalidInput):
        setup.set_use_case_binding("scoring", mode="sideways")


def test_endpoint_mode_requires_endpoint_and_model():
    setup, _ = _stack()
    with pytest.raises(InvalidInput):
        setup.set_use_case_binding("scoring", mode="endpoint", endpoint_id="", model="m")
    with pytest.raises(InvalidInput):
        setup.set_use_case_binding("scoring", mode="endpoint", endpoint_id="x", model="")


def test_binding_to_missing_endpoint_rejected():
    setup, _ = _stack()
    with pytest.raises(InvalidInput):
        setup.set_use_case_binding(
            "scoring", mode="endpoint", endpoint_id="does-not-exist", model="m"
        )


def test_deleted_bound_endpoint_falls_back_gracefully():
    setup, endpoints = _stack()
    _seed_ladder(setup)
    eid = endpoints.add_endpoint(
        base_url="https://openrouter.ai/api/v1", probe=False
    )["id"]
    setup.set_use_case_binding("scoring", mode="endpoint", endpoint_id=eid, model="m")
    endpoints.delete_endpoint(eid)
    # The binding record survives but the endpoint is gone -> resolve to base ladder.
    ladder = setup.resolve_use_case_ladder("scoring", endpoint_resolver=_resolver(endpoints))
    assert [t.model for t in ladder.tiers] == ["qwen-local", "deepseek-fallback"]


# === verified local-only private mode (P2-11) =============================
def test_local_only_drops_a_bound_cloud_endpoint():
    store = InMemoryAppConfigStore()
    setup, endpoints = _stack(store=store, local_only=True)
    # Only a private tier survives the local-only ladder filter.
    setup.set_tiers(
        [TierSettings(provider="ollama", base_url="http://localhost:11434", model="qwen-local")]
    )
    eid = endpoints.add_endpoint(
        base_url="https://api.deepseek.com/v1", probe=False
    )["id"]
    setup.set_use_case_binding(
        "drafting_cover_letter", mode="endpoint", endpoint_id=eid, model="deepseek-v4-flash"
    )
    ladder = setup.resolve_use_case_ladder(
        "drafting_cover_letter", endpoint_resolver=_resolver(endpoints)
    )
    # The cloud endpoint is refused; only the local ladder remains.
    assert [t.base_url for t in ladder.tiers] == ["http://localhost:11434"]


def test_local_only_keeps_a_bound_local_endpoint():
    store = InMemoryAppConfigStore()
    setup, endpoints = _stack(store=store, local_only=True)
    setup.set_tiers(
        [TierSettings(provider="ollama", base_url="http://localhost:11434", model="qwen-local")]
    )
    eid = endpoints.add_endpoint(
        base_url="http://127.0.0.1:8000/v1", probe=False
    )["id"]
    setup.set_use_case_binding("chat", mode="endpoint", endpoint_id=eid, model="qwen-fast")
    ladder = setup.resolve_use_case_ladder("chat", endpoint_resolver=_resolver(endpoints))
    assert ladder.tiers[0].base_url == "http://127.0.0.1:8000/v1"


# === smart-routing master flag override ===================================
def test_smart_routing_override_roundtrips():
    setup, _ = _stack()
    # Unset by default -> None so the caller uses the env/Settings default.
    assert setup.get_smart_routing() == {"enabled": None, "prefer_local": None}
    setup.set_smart_routing(enabled=False, prefer_local=True)
    assert setup.get_smart_routing() == {"enabled": False, "prefer_local": True}
    # Partial update leaves the other value untouched.
    setup.set_smart_routing(enabled=True)
    assert setup.get_smart_routing() == {"enabled": True, "prefer_local": True}


def test_smart_routing_shares_the_automation_prefs_record():
    """The master flag must not clobber other Automation prefs (one shared record)."""
    setup, _ = _stack()
    setup.set_automation_prefs(egress_locale="en-GB")
    setup.set_smart_routing(prefer_local=False)
    prefs = setup.get_automation_prefs()
    assert prefs.get("egress_locale") == "en-GB"
    assert setup.get_smart_routing()["prefer_local"] is False
