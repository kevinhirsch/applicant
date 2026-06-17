"""Lane C (engine side) — Cookbook-served models auto-register as LLM endpoints.

Hermetic: ``container.workspace`` is replaced by a tiny fake WorkspacePort (no
network) and the live model probe is mocked behind an injected httpx transport.
Covers: merge of Cookbook endpoints into ``list_endpoints`` (labeled, host
rewritten), no-clobber of a user-configured endpoint sharing the base URL, and
graceful degrade when the channel is unavailable / off / raises.
"""

from __future__ import annotations

import httpx

from applicant.adapters.storage.app_config_store import InMemoryAppConfigStore
from applicant.application.services.model_endpoint_service import ModelEndpointService
from applicant.ports.driven.workspace import WorkspaceError


class FakeWorkspace:
    """Minimal WorkspacePort double — no network."""

    def __init__(self, *, available=True, payload=None, raises=None):
        self._available = available
        self._payload = payload if payload is not None else {"models": []}
        self._raises = raises

    def available(self) -> bool:
        return self._available

    def local_models(self, *, owner=None):
        if self._raises is not None:
            raise self._raises
        return self._payload


def _transport(found="llama-cookbook"):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": found}]})
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def _service(workspace, *, transport=None, host="applicant-ui"):
    return ModelEndpointService(
        config_store=InMemoryAppConfigStore(),
        transport=transport or _transport(),
        workspace=workspace,
        cookbook_local_host=host,
    )


def _cookbook_payload(base_url="http://localhost:8001/v1", model_id="Qwen/Qwen2.5-7B"):
    return {"models": [{"model_id": model_id, "name": "Qwen2.5-7B", "base_url": base_url, "status": "ready"}]}


# === merge + labeling + host rewrite ========================================
def test_cookbook_endpoint_merged_and_labeled_with_host_rewrite():
    svc = _service(FakeWorkspace(payload=_cookbook_payload()))
    eps = svc.list_endpoints()
    cookbook = [e for e in eps if e.get("source") == "cookbook"]
    assert len(cookbook) == 1
    ep = cookbook[0]
    # localhost rewritten to the docker-network host so the engine can reach it.
    assert ep["base_url"] == "http://applicant-ui:8001/v1"
    assert ep["category"] == "cookbook"
    assert ep["read_only"] is True
    assert "Cookbook" in ep["name"]
    assert ep["has_key"] is False
    assert ep["models"] == ["llama-cookbook"]  # live probe result


def test_remote_serve_host_not_rewritten():
    svc = _service(FakeWorkspace(payload=_cookbook_payload(base_url="http://gpu-box:9000/v1")))
    ep = [e for e in svc.list_endpoints() if e.get("source") == "cookbook"][0]
    assert ep["base_url"] == "http://gpu-box:9000/v1"


# === no clobber =============================================================
def test_user_configured_endpoint_not_clobbered_by_cookbook():
    # The Cookbook reports the rewritten host (applicant-ui:8001); the user has
    # already configured that exact address -> Cookbook entry is dropped.
    svc = _service(FakeWorkspace(payload=_cookbook_payload()))
    svc.add_endpoint(base_url="http://applicant-ui:8001/v1", name="My vLLM", probe=False)
    eps = svc.list_endpoints()
    assert sum(1 for e in eps if _norm(e["base_url"]) == "http://applicant-ui:8001/v1") == 1
    survivor = next(e for e in eps if _norm(e["base_url"]) == "http://applicant-ui:8001/v1")
    assert survivor["name"] == "My vLLM"  # user record wins
    assert survivor.get("source") != "cookbook"


def _norm(u):
    return u.rstrip("/")


# === graceful degrade =======================================================
def test_degrades_when_channel_unavailable():
    svc = _service(FakeWorkspace(available=False, payload=_cookbook_payload()))
    assert [e for e in svc.list_endpoints() if e.get("source") == "cookbook"] == []


def test_degrades_when_workspace_none():
    svc = ModelEndpointService(config_store=InMemoryAppConfigStore(), transport=_transport(), workspace=None)
    assert [e for e in svc.list_endpoints() if e.get("source") == "cookbook"] == []


def test_degrades_when_workspace_raises():
    svc = _service(FakeWorkspace(raises=WorkspaceError("boom")))
    assert svc.list_endpoints() == []  # only cookbook would be present; none survive


def test_degrades_on_malformed_payload():
    svc = _service(FakeWorkspace(payload={"models": "not-a-list"}))
    assert [e for e in svc.list_endpoints() if e.get("source") == "cookbook"] == []
    svc2 = _service(FakeWorkspace(payload={"models": [42, {"base_url": ""}, {"no_url": 1}]}))
    assert [e for e in svc2.list_endpoints() if e.get("source") == "cookbook"] == []


def test_offline_cookbook_serve_still_listed():
    # Live probe fails (serve warming up) -> still listed, online False, falls
    # back to the reported model id so the dropdown isn't empty.
    def handler(request):
        raise httpx.ConnectError("refused")

    svc = _service(FakeWorkspace(payload=_cookbook_payload()), transport=httpx.MockTransport(handler))
    ep = [e for e in svc.list_endpoints() if e.get("source") == "cookbook"][0]
    assert ep["online"] is False
    assert ep["models"] == ["Qwen/Qwen2.5-7B"]
