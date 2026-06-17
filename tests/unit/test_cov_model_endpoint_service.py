"""ModelEndpointService branch coverage (FR-LLM-2; settings "Add Models").

Hermetic: the live model fetch is mocked behind an injected ``httpx`` transport so
nothing touches the network. Targets the previously-uncovered branches: get/set/
toggle by id, the no-base error paths, the brief response cache, vault key sealing
+ resolution (via the real ``PgCredentialStore``), preserving a sealed key on
re-add, the empty-but-online status, and the ``_parse_models`` shapes/edge cases.
"""

from __future__ import annotations

import httpx
import pytest

from applicant.adapters.storage.app_config_store import InMemoryAppConfigStore
from applicant.application.services.model_endpoint_service import (
    ModelEndpointService,
    _is_ollama,
    _looks_local,
    _normalize_base,
)
from applicant.core.errors import InvalidInput


def _openai_transport(calls: list | None = None) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request.url.path)
        if request.url.path.endswith("/api/tags"):
            return httpx.Response(200, json={"models": [{"name": "llama3.1:8b"}]})
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "gpt-4o"}, {"id": "o1"}]})
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def _service(transport=None, credentials=None) -> ModelEndpointService:
    return ModelEndpointService(
        config_store=InMemoryAppConfigStore(),
        credentials=credentials,
        transport=transport or _openai_transport(),
    )


# === pure helpers ==========================================================
def test_normalize_base_trims_trailing_slashes_and_space():
    assert _normalize_base("  https://x.ai/v1///  ") == "https://x.ai/v1"
    assert _normalize_base("") == ""
    assert _normalize_base(None) == ""  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:11434/v1",
        "http://127.0.0.1:8080",
        "http://192.168.1.5/v1",
        "http://10.0.0.2/v1",
        "http://myhost.local/v1",
    ],
)
def test_looks_local_true_for_private_hosts(url):
    assert _looks_local(url) is True


def test_looks_local_false_for_public_host():
    assert _looks_local("https://openrouter.ai/api/v1") is False


def test_is_ollama_detects_port_and_name():
    assert _is_ollama("http://localhost:11434/v1") is True
    assert _is_ollama("http://my-ollama-host/v1") is True
    assert _is_ollama("https://openrouter.ai/api/v1") is False


# === get / set / toggle by id =============================================
def test_get_endpoint_returns_record_and_none():
    svc = _service()
    ep = svc.add_endpoint(base_url="http://localhost:11434/v1", probe=False)
    rec = svc.get_endpoint(ep["id"])
    assert rec is not None and rec["base_url"] == "http://localhost:11434/v1"
    assert svc.get_endpoint("does-not-exist") is None


def test_set_enabled_sets_explicit_flag():
    svc = _service()
    ep = svc.add_endpoint(base_url="http://localhost:11434/v1", probe=False)
    svc.set_enabled(ep["id"], False)
    assert svc.get_endpoint(ep["id"])["is_enabled"] is False
    svc.set_enabled(ep["id"], True)
    assert svc.get_endpoint(ep["id"])["is_enabled"] is True


def test_models_for_id_returns_models_and_empty_for_unknown():
    svc = _service()
    ep = svc.add_endpoint(base_url="https://openrouter.ai/api/v1", api_key="sk", probe=False)
    assert svc.models_for_id(ep["id"], refresh=True) == ["gpt-4o", "o1"]
    assert svc.models_for_id("unknown") == []


# === probe / test error paths =============================================
def test_add_endpoint_requires_base_url():
    svc = _service()
    with pytest.raises(InvalidInput):
        svc.add_endpoint(base_url="   ")


def test_test_endpoint_requires_base_url():
    svc = _service()
    with pytest.raises(InvalidInput):
        svc.test_endpoint(base_url="")


def test_add_with_probe_false_skips_live_fetch():
    calls: list[str] = []
    svc = _service(transport=_openai_transport(calls))
    result = svc.add_endpoint(base_url="https://openrouter.ai/api/v1", api_key="sk", probe=False)
    assert result["models"] == []
    assert result["online"] is False
    assert calls == []  # no network call when probe is disabled


def test_empty_but_online_endpoint_reports_empty_status():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": []})  # reachable, zero models

    svc = _service(transport=httpx.MockTransport(handler))
    result = svc.add_endpoint(base_url="https://openrouter.ai/api/v1", api_key="sk")
    assert result["online"] is True
    assert result["models"] == []
    assert result["status"] == "empty"


# === response cache =======================================================
def test_models_are_cached_between_list_calls():
    calls: list[str] = []
    svc = _service(transport=_openai_transport(calls))
    svc.add_endpoint(base_url="https://openrouter.ai/api/v1", api_key="sk")  # one fetch (refresh)
    n_after_add = len(calls)
    svc.list_endpoints()  # served from cache (not a refresh) -> no new call
    assert len(calls) == n_after_add
    svc.list_endpoints(refresh=True)  # forced refresh -> a new call
    assert len(calls) == n_after_add + 1


# === re-add (dedupe + key preservation) ===================================
def test_readd_same_base_updates_in_place_and_preserves_key():
    svc = _service()  # no vault -> key kept inline
    first = svc.add_endpoint(
        base_url="https://openrouter.ai/api/v1", api_key="sk-secret", name="OR", probe=False
    )
    # Re-add the SAME base URL without a key: dedupes (same id) + preserves the key.
    second = svc.add_endpoint(base_url="https://openrouter.ai/api/v1/", probe=False)
    assert second["existing"] is True
    assert second["id"] == first["id"]
    rec = svc.get_endpoint(first["id"])
    assert rec["api_key"] == "sk-secret"  # preserved across the re-add
    # Only one endpoint persisted (deduped, not duplicated).
    assert len(svc.list_endpoints()) == 1


# === vault sealing (real PgCredentialStore, hermetic) =====================
def test_api_key_is_sealed_in_vault_not_stored_inline(credential_store):
    svc = ModelEndpointService(
        config_store=InMemoryAppConfigStore(),
        credentials=credential_store,
        transport=_openai_transport(),
    )
    ep = svc.add_endpoint(base_url="https://openrouter.ai/api/v1", api_key="sk-vault", probe=False)
    rec = svc.get_endpoint(ep["id"])
    # The plaintext key is NEVER persisted in the config record: only a vault ref.
    assert "api_key" not in rec
    assert rec["api_key_ref"] == f"model.endpoint.{ep['id']}"
    # has_key reflects the sealed ref in the UI shape.
    assert svc.list_endpoints()[0]["has_key"] is True
    # The live fetch resolves the key from the vault and sends it as a Bearer token.
    assert svc.models_for_id(ep["id"], refresh=True) == ["gpt-4o", "o1"]


def test_resolve_key_returns_empty_when_ref_missing_from_vault(credential_store):
    svc = ModelEndpointService(
        config_store=InMemoryAppConfigStore(),
        credentials=credential_store,
        transport=_openai_transport(),
    )
    # A record pointing at a non-existent vault ref resolves to no key (not an error).
    assert svc._resolve_key({"api_key_ref": "model.endpoint.ghost"}) == ""
    # And no key/ref at all also resolves to empty.
    assert svc._resolve_key({}) == ""


# === _parse_models shapes =================================================
def test_parse_models_ollama_shape_with_name_or_model_key():
    parsed = ModelEndpointService._parse_models(
        {"models": [{"name": "a"}, {"model": "b"}, {"foo": "skip"}, "junk"]}
    )
    assert parsed == ["a", "b"]


def test_parse_models_openai_shape_skips_idless_entries():
    parsed = ModelEndpointService._parse_models(
        {"data": [{"id": "gpt-4o"}, {"no_id": 1}, "junk", {"id": ""}]}
    )
    assert parsed == ["gpt-4o"]


def test_parse_models_unknown_shape_is_empty():
    assert ModelEndpointService._parse_models({"unexpected": 1}) == []
    assert ModelEndpointService._parse_models([]) == []  # type: ignore[arg-type]


# === SSRF guard ============================================================
def test_add_blocks_cloud_metadata_address():
    svc = _service()
    with pytest.raises(InvalidInput):
        svc.add_endpoint(base_url="http://169.254.169.254/latest", api_key="x")


def test_fetch_models_no_base_returns_offline():
    svc = _service()
    models, online, error = svc._fetch_models("", "")
    assert models == [] and online is False and error == "no base URL"
