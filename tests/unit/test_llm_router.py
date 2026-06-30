"""Tests for LLM smart routing (#298)."""

from __future__ import annotations

from applicant.adapters.llm.smart_router import SmartLlmRouter
from applicant.ports.driven.llm_router import Capability, CostTier, TaskType


class _FakeEndpointService:
    """Stub endpoint service returning configurable endpoint lists."""

    def __init__(self, endpoints: list[dict] | None = None):
        self._endpoints = endpoints or []

    def list_endpoints(self, *, refresh: bool = False):
        return self._endpoints


_LOCAL_ENDPOINT = {
    "id": "local-1",
    "name": "Ollama",
    "base_url": "http://localhost:11434/v1",
    "category": "local",
    "online": True,
    "models": ["llama3.1:8b"],
}

_CLOUD_ENDPOINT = {
    "id": "cloud-1",
    "name": "OpenAI GPT-4 Vision",
    "base_url": "https://api.openai.com/v1",
    "category": "api",
    "online": True,
    "models": ["gpt-4-vision"],
}

_OFFLINE_ENDPOINT = {
    "id": "offline-1",
    "name": "Local Offline",
    "base_url": "http://localhost:8080",
    "category": "local",
    "online": False,
    "models": [],
}


class TestSmartLlmRouter:
    def test_selects_cloud_for_reasoning_when_available(self):
        svc = _FakeEndpointService([_LOCAL_ENDPOINT, _CLOUD_ENDPOINT])
        router = SmartLlmRouter(svc)
        ep = router.select_endpoint(TaskType.REASONING)
        assert ep is not None
        assert ep["category"] == "api"  # cloud has function_calling + structured_output

    def test_selects_local_when_preferred(self):
        svc = _FakeEndpointService([_LOCAL_ENDPOINT, _CLOUD_ENDPOINT])
        router = SmartLlmRouter(svc)
        ep = router.select_endpoint(TaskType.CHAT, prefer_local=True)
        assert ep is not None
        assert ep["category"] == "local"

    def test_returns_none_when_no_online_endpoints(self):
        svc = _FakeEndpointService([_OFFLINE_ENDPOINT])
        router = SmartLlmRouter(svc)
        ep = router.select_endpoint(TaskType.CHAT)
        assert ep is None

    def test_returns_none_when_no_endpoints(self):
        svc = _FakeEndpointService([])
        router = SmartLlmRouter(svc)
        ep = router.select_endpoint(TaskType.CHAT)
        assert ep is None

    def test_lowest_cost_prefers_local(self):
        svc = _FakeEndpointService([_LOCAL_ENDPOINT, _CLOUD_ENDPOINT])
        router = SmartLlmRouter(svc)
        ep = router.select_endpoint(TaskType.CHAT, cost_tier=CostTier.LOWEST)
        assert ep is not None
        assert ep["category"] == "local"

    def test_list_available_returns_only_online(self):
        svc = _FakeEndpointService([_LOCAL_ENDPOINT, _OFFLINE_ENDPOINT])
        router = SmartLlmRouter(svc)
        available = router.list_available()
        assert len(available) == 1
        assert available[0]["id"] == "local-1"

    def test_health_reports_correct_counts(self):
        svc = _FakeEndpointService([_LOCAL_ENDPOINT, _CLOUD_ENDPOINT, _OFFLINE_ENDPOINT])
        router = SmartLlmRouter(svc)
        h = router.health()
        assert h["endpoints_total"] == 3
        assert h["endpoints_online"] == 2
        assert h["local_available"] == 1
        assert h["cloud_available"] == 1

    def test_selects_by_required_capability(self):
        svc = _FakeEndpointService([_LOCAL_ENDPOINT, _CLOUD_ENDPOINT])
        router = SmartLlmRouter(svc)
        # Only cloud endpoint has VISION
        ep = router.select_endpoint(
            TaskType.CHAT, required_capabilities={Capability.VISION}
        )
        assert ep is not None
        assert ep["category"] == "api"
