"""Smart-router status surfaced through GET /llm/tiers (dark-engine audit item 74).

``container.llm_router`` (the SmartLlmRouter that silently reorders the tier ladder
every resolve) was wired but never read by anything — the container comment said
"exposed for status/health" but no router actually read it, so a user had no way to
see which endpoint was actually serving a task, or why. These tests exercise the new
``_routing_status`` helper + its wiring into ``get_tiers`` directly against fakes, so
they stay hermetic (no Postgres, no real router/network).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from applicant.app.routers import setup as setup_router


class _FakeSettings:
    def __init__(self, *, smart_routing=True, prefer_local=True):
        self.llm_smart_routing = smart_routing
        self.llm_smart_routing_prefer_local = prefer_local


class _FakeSetupService:
    def __init__(self, tiers):
        self._tiers = tiers

    def get_tiers(self):
        return self._tiers


class _FakeRouter:
    def __init__(self, *, selected=None, health=None, select_error=False, health_error=False):
        self._selected = selected
        self._health = health if health is not None else {}
        self._select_error = select_error
        self._health_error = health_error
        self.select_calls = []

    def select_endpoint(self, task, *, cost_tier, prefer_local):
        self.select_calls.append((task, cost_tier, prefer_local))
        if self._select_error:
            raise RuntimeError("boom")
        return self._selected

    def health(self):
        if self._health_error:
            raise RuntimeError("boom")
        return self._health


def _container(*, settings=None, router=None, tiers=None):
    return SimpleNamespace(
        settings=settings or _FakeSettings(),
        llm_router=router,
        setup_service=_FakeSetupService(tiers if tiers is not None else []),
    )


def test_routing_disabled_when_smart_routing_off():
    container = _container(
        settings=_FakeSettings(smart_routing=False),
        router=_FakeRouter(selected={"name": "local", "base_url": "http://localhost:11434"}),
    )
    out = setup_router._routing_status(container)
    assert out == {
        "enabled": False,
        "prefer_local": True,
        "active_endpoint": None,
        "reordered": False,
        "health": None,
    }


def test_routing_enabled_but_no_router_wired():
    """LLM_SMART_ROUTING=true but the router was never constructed (no endpoints)."""
    container = _container(settings=_FakeSettings(smart_routing=True), router=None)
    out = setup_router._routing_status(container)
    assert out["enabled"] is True
    assert out["active_endpoint"] is None
    assert out["health"] is None
    assert out["reordered"] is False


def test_routing_reports_active_endpoint_and_reorder():
    tiers = [
        {"provider": "openrouter", "base_url": "https://openrouter.ai/api/v1", "model": "gpt-4o-mini"},
        {"provider": "ollama", "base_url": "http://localhost:11434", "model": "llama3.1"},
    ]
    router = _FakeRouter(
        selected={"name": "local-ollama", "base_url": "http://localhost:11434/"},
        health={"endpoints_total": 2, "endpoints_online": 2, "local_available": 1,
                "cloud_available": 1, "has_local_fallback": True},
    )
    container = _container(router=router, tiers=tiers)
    out = setup_router._routing_status(container)

    assert out["enabled"] is True
    assert out["active_endpoint"] == {"name": "local-ollama", "base_url": "http://localhost:11434/"}
    # Selected endpoint's base_url differs from the configured Level-1 tier -> reordered.
    assert out["reordered"] is True
    assert out["health"]["has_local_fallback"] is True
    # The router was asked with the real prefer-local policy from settings.
    assert router.select_calls[0][2] is True


def test_routing_not_reordered_when_selected_matches_level_one():
    tiers = [{"provider": "ollama", "base_url": "http://localhost:11434/", "model": "llama3.1"}]
    router = _FakeRouter(selected={"name": "local-ollama", "base_url": "http://localhost:11434"})
    container = _container(router=router, tiers=tiers)
    out = setup_router._routing_status(container)
    assert out["reordered"] is False
    assert out["active_endpoint"]["name"] == "local-ollama"


def test_routing_survives_router_exceptions():
    """A misbehaving router must never break the tiers endpoint (defensive, matches
    order_ladder_by_router's own never-strand-the-engine contract)."""
    router = _FakeRouter(select_error=True, health_error=True)
    container = _container(router=router, tiers=[{"base_url": "http://x"}])
    out = setup_router._routing_status(container)
    assert out["enabled"] is True
    assert out["active_endpoint"] is None
    assert out["health"] is None


def test_routing_no_selection_leaves_active_endpoint_none():
    router = _FakeRouter(selected=None, health={"endpoints_total": 0})
    container = _container(router=router, tiers=[{"base_url": "http://x"}])
    out = setup_router._routing_status(container)
    assert out["active_endpoint"] is None
    assert out["reordered"] is False
    assert out["health"] == {"endpoints_total": 0}


def test_get_tiers_route_includes_routing_key():
    svc = _FakeSetupService([{"provider": "ollama", "model": "llama3.1", "base_url": "http://localhost:11434"}])
    router = _FakeRouter(selected={"name": "local-ollama", "base_url": "http://localhost:11434"})
    container = _container(router=router, tiers=svc.get_tiers())
    container.setup_service = svc

    body = setup_router.get_tiers(svc=svc, container=container)

    assert body["tiers"] == svc.get_tiers()
    assert "routing" in body
    assert body["routing"]["enabled"] is True
    assert body["routing"]["active_endpoint"]["name"] == "local-ollama"


def test_norm_base_helper_ignores_case_scheme_trailing_slash():
    assert setup_router._norm_base("HTTP://Localhost:11434/") == "http://localhost:11434"
    assert setup_router._norm_base("") == ""
    assert setup_router._norm_base(None) == ""


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
