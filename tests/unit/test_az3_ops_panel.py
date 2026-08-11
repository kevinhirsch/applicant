"""AZ3 (#842) — the ops panel contract (source assertions).

The panel is browser-rendered HTML/JS (full E2E belongs in the P0-6 Playwright harness),
so here we pin the load-bearing contract at the source level, like the repo's other JS gates.
"""
from __future__ import annotations
from pathlib import Path

import pytest

PANEL = Path(__file__).resolve().parents[2] / "a0-applicant/webui/ops.html"


@pytest.fixture(scope="module")
def html() -> str:
    return PANEL.read_text(encoding="utf-8")


class TestOpsPanel:
    """Source-level assertions for the ops panel."""

    def test_tools_via_callJsonApi(self, html):
        assert 'callJsonApi("ops", { action: "tools" }' in html

    def test_set_tool_via_callJsonApi(self, html):
        assert 'action: "set_tool"' in html

    def test_history_via_callJsonApi(self, html):
        assert 'action: "history"' in html

    def test_detections_via_callJsonApi(self, html):
        assert 'action: "detections"' in html

    def test_logs_via_callJsonApi(self, html):
        assert 'action: "logs"' in html

    def test_campaign_picker(self, html):
        assert 'callJsonApi("campaigns", { action: "list" }' in html

    def test_fatalError_line(self, html):
        assert "fatalError" in html

    def test_empty_state_no_campaigns(self, html):
        assert "No campaigns" in html or "Select a campaign" in html
