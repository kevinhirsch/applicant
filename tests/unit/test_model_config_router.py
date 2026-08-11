"""EPIC MODEL-CONFIG — the Settings model-configuration router surface.

Exercises the new /api/setup/llm/use-cases (GET/PUT/DELETE) and
/api/setup/llm/smart-routing (GET/PUT) endpoints against a fake container holding
REAL SetupService + ModelEndpointService instances (sharing one in-memory config
store), with the LLM gate bypassed. Hermetic: model endpoints are added with
``probe=False`` so nothing touches the network.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from applicant.adapters.storage.app_config_store import InMemoryAppConfigStore
from applicant.app.deps import get_container, require_llm_configured
from applicant.app.main import create_app
from applicant.application.services.model_endpoint_service import ModelEndpointService
from applicant.application.services.setup_service import SetupService
from applicant.ports.driving.setup_wizard import TierSettings


@pytest.fixture
def container():
    store = InMemoryAppConfigStore()
    setup = SetupService(config_store=store)
    setup.set_tiers(
        [
            TierSettings(
                provider="ollama", base_url="http://localhost:11434", model="qwen-local"
            )
        ]
    )
    endpoints = ModelEndpointService(config_store=store, credentials=None)
    settings = SimpleNamespace(
        llm_smart_routing=True,
        llm_smart_routing_prefer_local=True,
        llm_preset_scoring_model="",
        llm_preset_drafting_model="deepseek-v4-flash",
        llm_preset_research_model="",
        llm_preset_chat_model="",
        llm_preset_embeddings_model="",
    )
    return SimpleNamespace(
        setup_service=setup,
        model_endpoint_service=endpoints,
        settings=settings,
        llm_router=None,
    )


@pytest.fixture
def client(container):
    app = create_app()
    app.dependency_overrides[require_llm_configured] = lambda: None
    app.dependency_overrides[get_container] = lambda: container
    return TestClient(app)


def test_get_use_cases_lists_catalog_with_presets(client):
    resp = client.get("/api/setup/llm/use-cases")
    assert resp.status_code == 200
    body = resp.json()
    keys = {r["key"] for r in body["use_cases"]}
    # Every documented use case is present and configurable.
    assert {"scoring", "drafting_cover_letter", "chat", "embeddings"} <= keys
    # Fresh install: everything defaults to the shared ladder.
    assert all(r["mode"] == "default" for r in body["use_cases"])
    # The drafting preset model is surfaced (env-overridable) from Settings.
    drafting = next(r for r in body["use_cases"] if r["key"] == "drafting_cover_letter")
    assert drafting["preset_model"] == "deepseek-v4-flash"
    # Smart-routing master flag reflects the env default when not overridden.
    assert body["smart_routing"] == {
        "enabled": True,
        "prefer_local": True,
        "overridden": False,
    }


def test_bind_use_case_to_endpoint_then_read_back(client, container):
    eid = container.model_endpoint_service.add_endpoint(
        base_url="https://openrouter.ai/api/v1", name="OpenRouter", probe=False
    )["id"]
    resp = client.put(
        "/api/setup/llm/use-cases/drafting_cover_letter",
        json={"mode": "endpoint", "endpoint_id": eid, "model": "deepseek-v4-flash"},
    )
    assert resp.status_code == 204
    body = client.get("/api/setup/llm/use-cases").json()
    row = next(r for r in body["use_cases"] if r["key"] == "drafting_cover_letter")
    assert row["mode"] == "endpoint"
    assert row["endpoint_id"] == eid
    assert row["model"] == "deepseek-v4-flash"
    assert row["endpoint_name"] == "OpenRouter"
    assert row["endpoint_missing"] is False


def test_bind_to_unknown_endpoint_is_400(client):
    resp = client.put(
        "/api/setup/llm/use-cases/scoring",
        json={"mode": "endpoint", "endpoint_id": "nope", "model": "m"},
    )
    assert resp.status_code == 400


def test_bind_unknown_use_case_is_400(client):
    resp = client.put(
        "/api/setup/llm/use-cases/not_real",
        json={"mode": "default"},
    )
    assert resp.status_code == 400


def test_clear_use_case_resets_to_default(client, container):
    eid = container.model_endpoint_service.add_endpoint(
        base_url="https://x.ai/v1", probe=False
    )["id"]
    client.put(
        "/api/setup/llm/use-cases/chat",
        json={"mode": "endpoint", "endpoint_id": eid, "model": "m"},
    )
    resp = client.delete("/api/setup/llm/use-cases/chat")
    assert resp.status_code == 204
    body = client.get("/api/setup/llm/use-cases").json()
    row = next(r for r in body["use_cases"] if r["key"] == "chat")
    assert row["mode"] == "default"


def test_smart_routing_get_and_override(client):
    # Default reflects Settings.
    body = client.get("/api/setup/llm/smart-routing").json()
    assert body["enabled"] is True and body["overridden"] is False
    # Override the master flag off.
    assert client.put("/api/setup/llm/smart-routing", json={"enabled": False}).status_code == 204
    body = client.get("/api/setup/llm/smart-routing").json()
    assert body["enabled"] is False
    assert body["prefer_local"] is True  # untouched -> still the Settings default
    assert body["overridden"] is True
