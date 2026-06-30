"""Coverage: model-endpoint ROUTER behavior (src/applicant/app/routers/model_endpoints.py).

The existing integration suite exercises the service and the add/list happy paths; this
file drives the router-level branches that were uncovered: the ``/test`` probe route, the
PATCH enable/disable toggle (+ 404), the DELETE route, the per-endpoint ``/models`` route
(+ 404), and the 400 error mapping when the service raises ``InvalidInput`` (bad/SSRF
base URL). The provider call is mocked behind an injected ``httpx`` transport so every
test is hermetic (no network).
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
        if path.endswith("/api/tags"):
            return httpx.Response(200, json={"models": [{"name": "llama3.1:8b"}, {"name": "qwen2"}]})
        if path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "anthropic/claude-3.5"}]})
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def _service() -> ModelEndpointService:
    return ModelEndpointService(
        config_store=InMemoryAppConfigStore(),
        credentials=None,
        transport=_mock_transport(),
    )


@pytest.fixture
def client():
    app = create_app()
    # Swap in a hermetic service so the route's live fetch never hits the network.
    # Container is frozen after construction; bypass with object.__setattr__ for test.
    object.__setattr__(app.state.container, "model_endpoint_service", _service())
    with TestClient(app) as c:
        yield c


# --- POST /test : probe without persisting ----------------------------------
def test_test_route_probes_without_saving(client):
    res = client.post(
        "/api/model-endpoints/test",
        data={"base_url": "https://openrouter.ai/api/v1", "api_key": "sk-test"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["online"] is True
    assert body["models"] == ["anthropic/claude-3.5"]
    # The probe must NOT persist anything (the form's "Test" button).
    assert client.get("/api/model-endpoints").json() == []


def test_test_route_blank_url_returns_400(client):
    # The service raises InvalidInput on an empty base URL -> router maps to 400.
    res = client.post("/api/model-endpoints/test", data={"base_url": ""})
    assert res.status_code == 400
    assert "base URL" in res.json()["detail"]


def test_test_route_ssrf_metadata_returns_400(client):
    # The operator-URL SSRF guard rejects the cloud-metadata address -> 400.
    res = client.post(
        "/api/model-endpoints/test",
        data={"base_url": "http://169.254.169.254/v1", "api_key": "x"},
    )
    assert res.status_code == 400


# --- POST "" : add error path -----------------------------------------------
def test_add_blank_url_returns_400(client):
    res = client.post("/api/model-endpoints", data={"base_url": ""})
    assert res.status_code == 400
    assert "base URL" in res.json()["detail"]


def test_add_with_skip_probe_does_not_fetch(client):
    # skip_probe=true -> the endpoint is saved but NOT live-listed on add.
    res = client.post(
        "/api/model-endpoints",
        data={"base_url": "http://localhost:11434/v1", "skip_probe": "true"},
    )
    assert res.status_code == 200
    body = res.json()
    # No probe means offline + empty models on the add response itself.
    assert body["online"] is False
    assert body["models"] == []
    # The record still persisted.
    assert len(client.get("/api/model-endpoints").json()) == 1


# --- PATCH /{id} : toggle + 404 ---------------------------------------------
def test_patch_toggles_enabled_flag(client):
    add = client.post(
        "/api/model-endpoints", data={"base_url": "http://localhost:11434/v1"}
    ).json()
    ep_id = add["id"]
    assert client.get("/api/model-endpoints").json()[0]["is_enabled"] is True

    res = client.patch(f"/api/model-endpoints/{ep_id}")
    assert res.status_code == 200
    assert res.json() == {"ok": True}
    assert client.get("/api/model-endpoints").json()[0]["is_enabled"] is False

    # Toggling again flips it back on (real toggle, not a one-way disable).
    client.patch(f"/api/model-endpoints/{ep_id}")
    assert client.get("/api/model-endpoints").json()[0]["is_enabled"] is True


def test_patch_unknown_endpoint_returns_404(client):
    res = client.patch("/api/model-endpoints/does-not-exist")
    assert res.status_code == 404
    assert res.json()["detail"] == "unknown endpoint"


# --- DELETE /{id} -----------------------------------------------------------
def test_delete_removes_endpoint(client):
    add = client.post(
        "/api/model-endpoints", data={"base_url": "http://localhost:11434/v1"}
    ).json()
    ep_id = add["id"]
    assert len(client.get("/api/model-endpoints").json()) == 1

    res = client.delete(f"/api/model-endpoints/{ep_id}")
    assert res.status_code == 200
    assert res.json() == {"ok": True}
    assert client.get("/api/model-endpoints").json() == []


def test_delete_unknown_endpoint_is_idempotent(client):
    # DELETE on an unknown id is a no-op success (the registry simply stays empty).
    res = client.delete("/api/model-endpoints/never-existed")
    assert res.status_code == 200
    assert res.json() == {"ok": True}


# --- GET /{id}/models : live list + 404 -------------------------------------
def test_models_route_lists_for_known_endpoint(client):
    add = client.post(
        "/api/model-endpoints", data={"base_url": "http://localhost:11434/v1"}
    ).json()
    ep_id = add["id"]
    res = client.get(f"/api/model-endpoints/{ep_id}/models")
    assert res.status_code == 200
    assert res.json() == ["llama3.1:8b", "qwen2"]


def test_models_route_refresh_param_forces_fresh_fetch(client):
    add = client.post(
        "/api/model-endpoints", data={"base_url": "http://localhost:11434/v1"}
    ).json()
    ep_id = add["id"]
    res = client.get(f"/api/model-endpoints/{ep_id}/models", params={"refresh": "true"})
    assert res.status_code == 200
    assert res.json() == ["llama3.1:8b", "qwen2"]


def test_models_route_unknown_endpoint_returns_404(client):
    res = client.get("/api/model-endpoints/does-not-exist/models")
    assert res.status_code == 404
    assert res.json()["detail"] == "unknown endpoint"


# --- GET "" refresh flag flows through to the service ------------------------
def test_list_with_refresh_flag(client):
    client.post("/api/model-endpoints", data={"base_url": "http://localhost:11434/v1"})
    res = client.get("/api/model-endpoints", params={"refresh": "true"})
    assert res.status_code == 200
    listed = res.json()
    assert len(listed) == 1
    assert listed[0]["models"] == ["llama3.1:8b", "qwen2"]
    assert listed[0]["category"] == "local"
