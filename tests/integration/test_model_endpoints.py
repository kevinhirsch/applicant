"""Model-endpoint flow: add a local/cloud endpoint and auto-list its models.

The live model fetch is mocked behind an injected ``httpx`` transport so these tests
never touch the network (hermetic). Covers both a remote (OpenRouter-style) endpoint
that lists models via ``GET {base}/models`` and a local (Ollama-style) endpoint that
lists models via ``GET {base}/api/tags``.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from applicant.adapters.storage.app_config_store import InMemoryAppConfigStore
from applicant.app.main import create_app
from applicant.application.services.model_endpoint_service import ModelEndpointService


def _mock_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        # Ollama lists models at /api/tags.
        if path.endswith("/api/tags"):
            return httpx.Response(200, json={"models": [{"name": "llama3.1:8b"}, {"name": "qwen2"}]})
        # OpenAI/OpenRouter list models at /models with a Bearer key.
        if path.endswith("/models"):
            assert request.headers.get("Authorization", "").startswith("Bearer "), (
                "remote model listing must send the API key server-side"
            )
            return httpx.Response(200, json={"data": [{"id": "anthropic/claude-3.5"}, {"id": "openai/gpt-4o"}]})
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def _service() -> ModelEndpointService:
    return ModelEndpointService(
        config_store=InMemoryAppConfigStore(),
        credentials=None,
        transport=_mock_transport(),
    )


def test_remote_endpoint_lists_models_on_add():
    svc = _service()
    result = svc.add_endpoint(base_url="https://openrouter.ai/api/v1", api_key="sk-test")
    assert result["online"] is True
    assert result["status"] == "online"
    assert result["models"] == ["anthropic/claude-3.5", "openai/gpt-4o"]
    # The list endpoint returns the same models for the dropdowns.
    listed = svc.list_endpoints()
    assert len(listed) == 1
    assert listed[0]["category"] == "api"
    assert listed[0]["models"] == ["anthropic/claude-3.5", "openai/gpt-4o"]


def test_local_endpoint_lists_models_on_add():
    svc = _service()
    result = svc.add_endpoint(base_url="http://localhost:11434/v1")
    assert result["online"] is True
    assert result["models"] == ["llama3.1:8b", "qwen2"]
    listed = svc.list_endpoints()
    assert listed[0]["category"] == "local"
    assert listed[0]["models"] == ["llama3.1:8b", "qwen2"]


def test_test_endpoint_does_not_persist():
    svc = _service()
    probe = svc.test_endpoint(base_url="https://openrouter.ai/api/v1", api_key="sk-test")
    assert probe["online"] is True
    assert probe["models"]
    assert svc.list_endpoints() == []  # Test must not save anything.


def test_unreachable_endpoint_reports_offline():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    svc = ModelEndpointService(
        config_store=InMemoryAppConfigStore(),
        credentials=None,
        transport=httpx.MockTransport(handler),
    )
    result = svc.add_endpoint(base_url="https://bad.example.com/v1", api_key="sk-x")
    assert result["online"] is False
    assert result["status"] == "offline"
    assert result["models"] == []
    # Offline endpoints still list (so the UI can show them), with no models.
    assert svc.list_endpoints()[0]["online"] is False


def test_toggle_and_delete():
    svc = _service()
    ep = svc.add_endpoint(base_url="http://localhost:11434/v1")
    ep_id = ep["id"]
    svc.toggle_enabled(ep_id)
    assert svc.list_endpoints()[0]["is_enabled"] is False
    svc.delete_endpoint(ep_id)
    assert svc.list_endpoints() == []


def test_ssrf_metadata_address_rejected():
    from applicant.core.errors import InvalidInput

    svc = _service()
    with pytest.raises(InvalidInput):
        svc.add_endpoint(base_url="http://169.254.169.254/v1", api_key="x")


# --- HTTP-level tests (router + container) ---------------------------------


@pytest.fixture
def client_with_mock():
    app = create_app()
    # Swap in a hermetic service so the route's live fetch never hits the network.
    app.state.container.model_endpoint_service = _service()
    with TestClient(app) as c:
        yield c


def test_add_and_list_over_http(client_with_mock):
    res = client_with_mock.post(
        "/api/model-endpoints",
        data={"base_url": "https://openrouter.ai/api/v1", "api_key": "sk-test"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["online"] is True
    assert "openai/gpt-4o" in body["models"]

    listed = client_with_mock.get("/api/model-endpoints").json()
    assert len(listed) == 1
    assert listed[0]["models"]


def test_local_add_over_http(client_with_mock):
    res = client_with_mock.post(
        "/api/model-endpoints",
        data={"base_url": "http://localhost:11434/v1"},
    )
    assert res.status_code == 200
    assert res.json()["models"] == ["llama3.1:8b", "qwen2"]


def test_endpoints_route_is_ungated(client_with_mock):
    # Listing endpoints must work BEFORE the LLM gate opens (it is how you open it).
    assert client_with_mock.get("/api/model-endpoints").status_code == 200


def test_pick_endpoint_model_opens_gate(client_with_mock):
    # Add a local endpoint, then choose its model -> the LLM gate opens.
    add = client_with_mock.post(
        "/api/model-endpoints", data={"base_url": "http://localhost:11434/v1"}
    ).json()
    ep_id = add["id"]
    assert client_with_mock.get("/api/setup/status").json()["gate_open"] is False

    res = client_with_mock.post(
        "/api/setup/llm/from-endpoint",
        json={"endpoint_id": ep_id, "model": "llama3.1:8b"},
    )
    assert res.status_code == 204
    assert client_with_mock.get("/api/setup/status").json()["gate_open"] is True
    # A gated route now works.
    assert client_with_mock.get("/api/campaigns").status_code == 200
