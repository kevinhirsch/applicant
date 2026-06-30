"""Unit tests for the MCP server surface (Issue #308).

Tests verify that:
- MCP tool descriptors are correctly wired from the container
- Tool functions return the expected data shapes
- The mount_mcp function handles missing fastapi_mcp gracefully
- The router is registered under /mcp
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from applicant.app.routers.mcp import (
    _fastapi_mcp_available,
    _tool_get_applications,
    _tool_get_attributes,
    _tool_get_pending_actions,
    _tool_health_check,
    _tool_list_campaigns,
    mount_mcp,
    wire_mcp_tools,
)


class TestMCPTools:
    """MCP tool functions return correct data from storage."""

    def test_list_campaigns(self):
        """list_campaigns returns campaign metadata."""
        storage = MagicMock()
        campaign = MagicMock()
        campaign.id = "camp-1"
        campaign.name = "Test Campaign"
        campaign.job_title = "Engineer"
        campaign.status = "active"
        storage.campaigns.list.return_value = [campaign]

        result = _tool_list_campaigns(storage)
        assert len(result) == 1
        assert result[0]["name"] == "Test Campaign"
        assert result[0]["job_title"] == "Engineer"

    def test_get_attributes(self):
        """get_attributes returns attribute cloud entries."""
        storage = MagicMock()
        attr = MagicMock()
        attr.id = "attr-1"
        attr.name = "full_name"
        attr.value = "Jane Doe"
        attr.category = "personal"
        storage.attributes.list.return_value = [attr]

        result = _tool_get_attributes(storage)
        assert len(result) == 1
        assert result[0]["name"] == "full_name"
        assert result[0]["value"] == "Jane Doe"

    def test_get_applications(self):
        """get_applications returns application data."""
        storage = MagicMock()
        app = MagicMock()
        app.id = "app-1"
        app.campaign_id = "camp-1"
        app.status = "in_progress"
        app.url = "https://example.com/job"
        storage.applications.list.return_value = [app]

        result = _tool_get_applications(storage)
        assert len(result) == 1
        assert result[0]["id"] == "app-1"
        assert result[0]["status"] == "in_progress"

    def test_get_pending_actions(self):
        """get_pending_actions returns open pending actions."""
        storage = MagicMock()
        pa = MagicMock()
        pa.id = "pa-1"
        pa.kind = "missing_attr"
        pa.title = "Need your name"
        pa.campaign_id = "camp-1"
        pa.application_id = "app-1"
        pa.payload = {"field": "name"}
        storage.pending_actions.list_open.return_value = [pa]

        result = _tool_get_pending_actions(storage)
        assert len(result) == 1
        assert result[0]["kind"] == "missing_attr"

    def test_get_pending_actions_failure(self):
        """get_pending_actions handles storage failures gracefully."""
        storage = MagicMock()
        storage.pending_actions.list_open.side_effect = Exception("storage error")

        result = _tool_get_pending_actions(storage)
        assert result == []

    def test_health_check_with_container(self):
        """health check returns ok when container is present."""
        state = MagicMock()
        container = MagicMock()
        container.storage = MagicMock()
        container.llm = MagicMock()
        state.container = container

        result = _tool_health_check(state)
        assert result["healthy"] is True
        assert result["status"] == "ok"

    def test_health_check_no_container(self):
        """health check returns not healthy when container is absent."""
        state = MagicMock()
        state.container = None

        result = _tool_health_check(state)
        assert result["healthy"] is False
        assert result["status"] == "no_container"


class TestWireMCPTools:
    """wire_mcp_tools returns tool descriptors."""

    def test_wire_mcp_tools_with_container(self):
        """wire_mcp_tools returns tool list when storage is present."""
        container = MagicMock()
        container.storage = MagicMock()

        tools = wire_mcp_tools(container)
        names = [t["name"] for t in tools]
        assert "list_campaigns" in names
        assert "get_attributes" in names
        assert "get_applications" in names
        assert "get_pending_actions" in names
        assert "health" in names

    def test_wire_mcp_tools_no_storage(self):
        """wire_mcp_tools returns only health when storage is absent."""
        container = MagicMock()
        container.storage = None

        tools = wire_mcp_tools(container)
        names = [t["name"] for t in tools]
        assert "list_campaigns" not in names
        assert "health" in names


class TestMountMCP:
    """mount_mcp handles fastapi_mcp availability gracefully."""

    def test_mount_mcp_no_fastapi_mcp(self):
        """When fastapi_mcp is not available, mount is a no-op."""
        if _fastapi_mcp_available:
            pytest.skip("fastapi_mcp is installed, cannot test without it")

        app = MagicMock()
        # Should not raise
        mount_mcp(app)

    def test_mount_mcp_with_fastapi_mcp(self):
        """When fastapi_mcp is installed, mount adds routes to the app.

        Checks via app.routes — no SSE/blocking GET is issued.
        """
        if not _fastapi_mcp_available:
            pytest.skip("fastapi_mcp not installed (install with uv sync --extra mcp)")

        from fastapi import FastAPI
        app = FastAPI()
        route_count_before = len(app.routes)
        mount_mcp(app)
        # fastapi_mcp should add at least one route (e.g. the MCP SSE endpoint)
        assert len(app.routes) > route_count_before, (
            "mount_mcp should add at least one route when fastapi_mcp is installed"
        )

    def test_router_prefix(self):
        """The MCP router is registered under /mcp."""
        from applicant.app.routers.mcp import router
        assert router.prefix == "/mcp"
        assert "mcp" in router.tags


class TestMCPToolsRegistration:
    """wire_mcp_tools always registers the five expected tools regardless of fastapi_mcp."""

    _EXPECTED_TOOL_NAMES = frozenset(
        {"list_campaigns", "get_attributes", "get_applications", "get_pending_actions", "health"}
    )

    def test_all_five_tools_registered_with_storage(self):
        """wire_mcp_tools returns all five tools when storage is present."""
        container = MagicMock()
        container.storage = MagicMock()

        tools = wire_mcp_tools(container)
        names = {t["name"] for t in tools}
        assert names == self._EXPECTED_TOOL_NAMES

    def test_tool_descriptors_have_required_fields(self):
        """Every tool descriptor has name, description, and handler."""
        container = MagicMock()
        container.storage = MagicMock()

        tools = wire_mcp_tools(container)
        for tool in tools:
            assert "name" in tool, f"Tool {tool} missing 'name'"
            assert "description" in tool, f"Tool {tool!r} missing 'description'"
            assert "handler" in tool, f"Tool {tool!r} missing 'handler'"
            assert callable(tool["handler"]), f"Tool {tool['name']} handler is not callable"

    def test_tool_handlers_are_callable(self):
        """Each tool handler can be invoked without error against mock storage."""
        container = MagicMock()
        container.storage = MagicMock()
        container.storage.campaigns.list.return_value = []
        container.storage.attributes.list.return_value = []
        container.storage.applications.list.return_value = []
        container.storage.pending_actions.list_open.return_value = []

        tools = wire_mcp_tools(container)
        for tool in tools:
            result = tool["handler"]()
            # All handlers should return a list or dict
            assert isinstance(result, (list, dict)), (
                f"Tool {tool['name']} returned unexpected type {type(result)}"
            )
