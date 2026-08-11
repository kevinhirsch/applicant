"""Positive controls: the read/observe lane is unaffected by bypass guards.

These tests prove the happy-path lanes that the negative tests depend on:
- MCP tool listing returns the exact 5 read-only tools.
- The engine read lane (list_campaigns) works via MCP call.
- The capture/observe lane is never gated, even with a final-submit intent.

Negative tests (refusals) live in test_gate_bypass_negative.py — those are not
duplicated here.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from applicant.app.routers.mcp import _NATIVE_TOOL_SPECS, mount_mcp
from applicant.core.rules.computer_use import DesktopAction, ensure_desktop_action_allowed


@pytest.fixture(autouse=True)
def _no_cache() -> None:
    """Parallel xdist safety — follows existing test convention."""
    return None


# ---------------------------------------------------------------------------
# Positive control A: MCP tool listing
# ---------------------------------------------------------------------------

class TestMCPToolListing:
    """The MCP surface advertises exactly the 5 read-only tools."""

    @staticmethod
    def _build_app() -> FastAPI:
        container = MagicMock()
        container.storage = MagicMock()
        container.storage.campaigns.list.return_value = []
        container.storage.attributes.list.return_value = []
        container.storage.applications.list.return_value = []
        container.storage.pending_actions.list_open.return_value = []
        container.llm = MagicMock()
        container.setup_service.is_setup_gate_open.return_value = True

        app = FastAPI()
        app.state.container = container
        mount_mcp(app)
        return app

    def test_tool_list_returns_exactly_5_read_only_tools(self) -> None:
        """POST /mcp/tools/list returns exactly 5 tools matching the
        _NATIVE_TOOL_SPECS allowlist."""
        app = self._build_app()
        with TestClient(app) as client:
            resp = client.post("/mcp/tools/list")
        assert resp.status_code == 200
        body = resp.json()
        tools = body["tools"]
        assert len(tools) == 5, f"Expected 5 tools, got {len(tools)}"
        returned_names = {t["name"] for t in tools}
        expected_names = {spec["name"] for spec in _NATIVE_TOOL_SPECS}
        assert returned_names == expected_names, (
            f"Tool names mismatch: {returned_names} != {expected_names}"
        )


# ---------------------------------------------------------------------------
# Positive control B: Engine read lane via MCP call
# ---------------------------------------------------------------------------

class TestMCPReadLane:
    """The engine read lane is unaffected by bypass guards."""

    @staticmethod
    def _build_app() -> FastAPI:
        container = MagicMock()
        container.storage = MagicMock()
        campaign = MagicMock()
        campaign.id = "camp-1"
        campaign.name = "Test Campaign"
        campaign.active = True
        container.storage.campaigns.list.return_value = [campaign]
        container.storage.attributes.list.return_value = []
        container.storage.applications.list.return_value = []
        container.storage.pending_actions.list_open.return_value = []
        container.llm = MagicMock()
        container.setup_service.is_setup_gate_open.return_value = True

        app = FastAPI()
        app.state.container = container
        mount_mcp(app)
        return app

    def test_call_list_campaigns_returns_is_error_false(self) -> None:
        """POST /mcp/tools/call with {name: list_campaigns} returns isError=False."""
        app = self._build_app()
        with TestClient(app) as client:
            resp = client.post(
                "/mcp/tools/call",
                json={"name": "list_campaigns"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("isError") is not True, f"Read tool returned error: {body}"


# ---------------------------------------------------------------------------
# Positive control C: Capture/observe lane is never gated
# ---------------------------------------------------------------------------

class TestCaptureObserveLane:
    """The capture/observe lane is never gated, even with a final-submit intent."""

    def test_capture_no_raise_with_final_submit_intent(self) -> None:
        """ensure_desktop_action_allowed(CAPTURE, intent='final_submit') does NOT raise."""
        # CAPTURE with an intent — should not raise
        ensure_desktop_action_allowed(DesktopAction.CAPTURE, intent="final_submit")

    def test_capture_no_raise_without_intent(self) -> None:
        """ensure_desktop_action_allowed(CAPTURE) with no arguments does NOT raise."""
        ensure_desktop_action_allowed(DesktopAction.CAPTURE)
