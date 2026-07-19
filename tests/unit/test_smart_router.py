import pytest

from applicant.adapters.llm.smart_router import SmartLlmRouter, order_ladder_by_router
from applicant.ports.driven.llm import TierLadder, TierConfig
from applicant.ports.driven.llm_router import Capability, CostTier, TaskType


class TestSmartLlmRouter:
    """Unit tests for SmartLlmRouter."""

    @pytest.fixture(autouse=True)
    def _noop_fixture(self) -> None:
        """Autouse fixture for parallel xdist safety (no cached state in this module)."""
        pass

    # ------------------------------------------------------------------
    # Helper: build a fake endpoint_service that returns endpoints from a
    # provided list, so tests do not depend on external infra.
    # ------------------------------------------------------------------

    @staticmethod
    def _make_service(endpoints: list[dict]) -> object:
        class FakeService:
            def list_endpoints(self, refresh: bool = False) -> list[dict]:
                return endpoints
        return FakeService()

    # ------------------------------------------------------------------
    # select_endpoint
    # ------------------------------------------------------------------

    def test_select_endpoint_when_empty_returns_none(self) -> None:
        """Empty endpoint list returns None from select_endpoint."""
        svc = self._make_service([])
        router = SmartLlmRouter(svc)
        result = router.select_endpoint(TaskType.CHAT)
        assert result is None

    def test_select_endpoint_returns_matching_online_endpoint(self) -> None:
        """An online API endpoint matching TaskType.CHAT is returned."""
        svc = self._make_service([
            {
                "id": "ep-1",
                "name": "test-api",
                "base_url": "https://api.example.com/v1",
                "category": "api",
                "online": True,
            },
        ])
        router = SmartLlmRouter(svc)
        result = router.select_endpoint(TaskType.CHAT)
        assert result is not None
        assert result["id"] == "ep-1"

    def test_select_endpoint_skips_offline(self) -> None:
        """Offline endpoints are skipped; None returned when only offline."""
        svc = self._make_service([
            {
                "id": "ep-off",
                "name": "offline-api",
                "base_url": "https://offline.example.com",
                "category": "api",
                "online": False,
            },
        ])
        router = SmartLlmRouter(svc)
        result = router.select_endpoint(TaskType.CHAT)
        assert result is None

    def test_select_endpoint_prefer_local(self) -> None:
        """With prefer_local=True, a local endpoint is chosen over cloud."""
        svc = self._make_service([
            {
                "id": "cloud",
                "name": "Cloud API",
                "base_url": "https://api.openai.com/v1",
                "category": "api",
                "online": True,
            },
            {
                "id": "local",
                "name": "Local Ollama",
                "base_url": "http://localhost:11434",
                "category": "local",
                "online": True,
            },
        ])
        router = SmartLlmRouter(svc)
        result = router.select_endpoint(TaskType.CHAT, prefer_local=True)
        assert result is not None
        assert result["id"] == "local"

    def test_select_endpoint_cost_tier_lowest(self) -> None:
        """CostTier.LOWEST prefers local endpoints."""
        svc = self._make_service([
            {
                "id": "cloud",
                "name": "Cloud API",
                "base_url": "https://api.openai.com/v1",
                "category": "api",
                "online": True,
            },
            {
                "id": "local",
                "name": "Local Ollama",
                "base_url": "http://localhost:11434",
                "category": "local",
                "online": True,
            },
        ])
        router = SmartLlmRouter(svc)
        result = router.select_endpoint(TaskType.CHAT, cost_tier=CostTier.LOWEST)
        assert result is not None
        assert result["id"] == "local"

    def test_select_endpoint_cost_tier_unlimited(self) -> None:
        """CostTier.UNLIMITED prefers cloud endpoints."""
        svc = self._make_service([
            {
                "id": "local",
                "name": "Local Ollama",
                "base_url": "http://localhost:11434",
                "category": "local",
                "online": True,
            },
            {
                "id": "cloud",
                "name": "Cloud API",
                "base_url": "https://api.openai.com/v1",
                "category": "api",
                "online": True,
            },
        ])
        router = SmartLlmRouter(svc)
        result = router.select_endpoint(TaskType.CHAT, cost_tier=CostTier.UNLIMITED)
        assert result is not None
        assert result["id"] == "cloud"

    # ------------------------------------------------------------------
    # health
    # ------------------------------------------------------------------

    def test_health_returns_expected_structure(self) -> None:
        """health() returns dict with correct counts."""
        svc = self._make_service([
            {
                "id": "ep-1",
                "name": "Local",
                "base_url": "http://localhost:11434",
                "category": "local",
                "online": True,
            },
            {
                "id": "ep-2",
                "name": "Cloud",
                "base_url": "https://api.example.com",
                "category": "api",
                "online": True,
            },
            {
                "id": "ep-3",
                "name": "Offline",
                "base_url": "https://offline.example.com",
                "category": "api",
                "online": False,
            },
        ])
        router = SmartLlmRouter(svc)
        h = router.health()
        assert h["endpoints_total"] == 3
        assert h["endpoints_online"] == 2
        assert h["local_available"] == 1
        assert h["cloud_available"] == 1
        assert h["has_local_fallback"] is True

    def test_health_no_online(self) -> None:
        """health() handles case with no online endpoints."""
        svc = self._make_service([
            {
                "id": "ep-off",
                "name": "Offline",
                "base_url": "https://offline.example.com",
                "category": "api",
                "online": False,
            },
        ])
        router = SmartLlmRouter(svc)
        h = router.health()
        assert h["endpoints_total"] == 1
        assert h["endpoints_online"] == 0
        assert h["local_available"] == 0
        assert h["cloud_available"] == 0
        assert h["has_local_fallback"] is False

    # ------------------------------------------------------------------
    # list_available
    # ------------------------------------------------------------------

    def test_list_available_filters_offline(self) -> None:
        """list_available returns only online endpoints."""
        svc = self._make_service([
            {
                "id": "ep-on",
                "name": "Online API",
                "base_url": "https://api.example.com",
                "category": "api",
                "online": True,
            },
            {
                "id": "ep-off",
                "name": "Offline API",
                "base_url": "https://offline.example.com",
                "category": "api",
                "online": False,
            },
        ])
        router = SmartLlmRouter(svc)
        available = router.list_available()
        assert len(available) == 1
        assert available[0]["id"] == "ep-on"
        assert available[0]["online"] is True

    def test_list_available_includes_capabilities(self) -> None:
        """list_available includes sorted capability names."""
        svc = self._make_service([
            {
                "id": "ep-1",
                "name": "Test API",
                "base_url": "https://api.example.com",
                "category": "api",
                "online": True,
            },
        ])
        router = SmartLlmRouter(svc)
        available = router.list_available()
        assert len(available) == 1
        caps = available[0]["capabilities"]
        # API endpoints get: CONTEXT_128K, FUNCTION_CALLING, STRUCTURED_OUTPUT, SYSTEM_PROMPT, TOOL_USE
        assert "SYSTEM_PROMPT" in caps
        assert "FUNCTION_CALLING" in caps
        assert "STRUCTURED_OUTPUT" in caps
        assert "TOOL_USE" in caps

    def test_list_available_empty_when_all_offline(self) -> None:
        """list_available returns [] when all endpoints are offline."""
        svc = self._make_service([
            {"id": "ep-1", "name": "X", "base_url": "https://x.com", "category": "api", "online": False},
        ])
        router = SmartLlmRouter(svc)
        assert router.list_available() == []

    # ------------------------------------------------------------------
    # order_ladder_by_router
    # ------------------------------------------------------------------

    def test_order_ladder_by_router_reorders(self) -> None:
        """When the selected endpoint's base_url matches a tier, that tier moves to front."""
        svc = self._make_service([
            {
                "id": "local-ep",
                "name": "Local Model",
                "base_url": "http://localhost:11434",
                "category": "local",
                "online": True,
            },
        ])
        router = SmartLlmRouter(svc)
        ladder = TierLadder(tiers=[
            TierConfig(provider="openai", base_url="https://api.openai.com/v1", model="gpt-4"),
            TierConfig(provider="ollama", base_url="http://localhost:11434", model="llama3"),
        ])
        result = order_ladder_by_router(ladder, router, task=TaskType.CHAT)
        assert result is not None
        reordered = result.tiers
        assert len(reordered) == 2
        assert reordered[0].provider == "ollama"
        assert reordered[0].base_url == "http://localhost:11434"
        assert reordered[1].provider == "openai"

    def test_order_ladder_no_match_returns_unchanged(self) -> None:
        """When no tier matches the selected endpoint, the ladder is returned unchanged."""
        svc = self._make_service([
            {
                "id": "cloud-ep",
                "name": "Cloud",
                "base_url": "https://api.other.com/v1",
                "category": "api",
                "online": True,
            },
        ])
        router = SmartLlmRouter(svc)
        ladder = TierLadder(tiers=[
            TierConfig(provider="ollama", base_url="http://localhost:11434", model="llama3"),
        ])
        result = order_ladder_by_router(ladder, router, task=TaskType.CHAT)
        assert result is not None
        assert result.tiers[0].provider == "ollama"

    def test_order_ladder_none_ladder_returns_none(self) -> None:
        """When ladder is None, order_ladder_by_router returns None."""
        svc = self._make_service([])
        router = SmartLlmRouter(svc)
        result = order_ladder_by_router(None, router, task=TaskType.CHAT)
        assert result is None

    def test_order_ladder_already_first(self) -> None:
        """When the preferred tier is already first, the ladder is unchanged."""
        svc = self._make_service([
            {
                "id": "local",
                "name": "Local",
                "base_url": "http://localhost:11434",
                "category": "local",
                "online": True,
            },
        ])
        router = SmartLlmRouter(svc)
        ladder = TierLadder(tiers=[
            TierConfig(provider="ollama", base_url="http://localhost:11434", model="llama3"),
            TierConfig(provider="openai", base_url="https://api.openai.com/v1", model="gpt-4"),
        ])
        result = order_ladder_by_router(ladder, router, task=TaskType.CHAT)
        assert result is not None
        assert result.tiers[0].provider == "ollama"
        assert result.tiers[1].provider == "openai"
