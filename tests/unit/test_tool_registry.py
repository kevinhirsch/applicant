import pytest

from applicant.adapters.tools.tool_registry import (
    DEFAULT_TOOLS,
    ToolDisabledError,
    ToolRegistry,
)
from applicant.core.errors import DomainError


class TestToolRegistry:
    """Unit tests for ToolRegistry (FR-UI-4)."""

    @pytest.fixture(autouse=True)
    def fresh_registry(self) -> None:
        """Provide a clean ToolRegistry for each test (in-memory mode, no sink)."""
        self.registry = ToolRegistry()

    # --- initial state ---

    def test_default_all_enabled(self):
        """All DEFAULT_TOOLS start enabled."""
        for tool in DEFAULT_TOOLS:
            assert self.registry.is_enabled(tool) is True

    def test_all_tools_keys_match_defaults(self):
        """all_tools() returns every DEFAULT_TOOLS key with correct count."""
        tools = self.registry.all_tools()
        assert set(tools.keys()) == set(DEFAULT_TOOLS)
        assert len(tools) == len(DEFAULT_TOOLS)

    def test_all_tools_values_all_true(self):
        """all_tools() returns True for every tool."""
        tools = self.registry.all_tools()
        assert all(tools.values()) is True

    # --- is_enabled ---

    def test_is_enabled_returns_true_for_default(self):
        assert self.registry.is_enabled("scoring") is True

    def test_is_enabled_returns_false_after_disable(self):
        self.registry.set_enabled("scoring", False)
        assert self.registry.is_enabled("scoring") is False

    def test_is_enabled_unknown_key_defaults_true(self):
        """Undefined tool keys default to True (extensibility, NFR-EXT-1)."""
        assert self.registry.is_enabled("unknown_tool") is True

    # --- set_enabled ---

    def test_set_enabled_toggles_off(self):
        self.registry.set_enabled("chat", False)
        assert self.registry.is_enabled("chat") is False

    def test_set_enabled_toggles_on(self):
        self.registry.set_enabled("chat", False)
        self.registry.set_enabled("chat", True)
        assert self.registry.is_enabled("chat") is True

    def test_set_enabled_reverts_disabled_tool(self):
        self.registry.set_enabled("web_research", False)
        self.registry.set_enabled("web_research", True)
        assert self.registry.is_enabled("web_research") is True

    def test_set_enabled_converts_to_bool(self):
        """Non-bool values are coerced to bool."""
        self.registry.set_enabled("chat", 1)
        assert self.registry.is_enabled("chat") is True
        self.registry.set_enabled("chat", 0)
        assert self.registry.is_enabled("chat") is False

    # --- ensure_enabled ---

    def test_ensure_enabled_passes_for_enabled(self):
        """Calling ensure_enabled on an enabled tool does not raise."""
        self.registry.ensure_enabled("scoring")  # no exception

    def test_ensure_enabled_raises_for_disabled(self):
        self.registry.set_enabled("scoring", False)
        with pytest.raises(ToolDisabledError, match="Scoring"):
            self.registry.ensure_enabled("scoring")

    def test_ensure_enabled_raises_tool_disabled_error_type(self):
        self.registry.set_enabled("notifications", False)
        with pytest.raises(ToolDisabledError):
            self.registry.ensure_enabled("notifications")

    # --- registry_view ---

    def test_registry_view_structure(self):
        view = self.registry.registry_view()
        assert isinstance(view, list)
        assert len(view) == len(DEFAULT_TOOLS)
        for entry in view:
            assert isinstance(entry, dict)
            assert "key" in entry
            assert "label" in entry
            assert "enabled" in entry
            assert entry["enabled"] is True

    def test_registry_view_after_toggle(self):
        self.registry.set_enabled("discovery", False)
        view = self.registry.registry_view()
        discovery = next(v for v in view if v["key"] == "discovery")
        assert discovery["enabled"] is False

    # --- ToolDisabledError hierarchy ---

    def test_tool_disabled_error_is_domain_error(self):
        assert issubclass(ToolDisabledError, DomainError)
        assert issubclass(ToolDisabledError, Exception)

    def test_tool_disabled_error_default_message(self):
        err = ToolDisabledError()
        assert isinstance(err, ToolDisabledError)

    # --- all_tools returns dict copy ---

    def test_all_tools_is_copy_not_reference(self):
        tools = self.registry.all_tools()
        tools["chat"] = False
        assert self.registry.is_enabled("chat") is True

    # --- set_enabled persist_not_required ---

    def test_set_enabled_no_persist_required(self):
        """set_enabled works in-memory without any sink."""
        reg = ToolRegistry()  # no sink; explicit fresh instance
        reg.set_enabled("prefill", False)
        assert reg.is_enabled("prefill") is False
        reg.set_enabled("prefill", True)
        assert reg.is_enabled("prefill") is True

