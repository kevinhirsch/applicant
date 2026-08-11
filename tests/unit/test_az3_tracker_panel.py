"""AZ3 (#840) — the tracker panel contract (source assertions).

The panel is browser-rendered HTML/JS (full E2E belongs in the P0-6 Playwright harness),
so here we pin the load-bearing contract at the source level, like the repo's other JS gates.
"""
from __future__ import annotations
from pathlib import Path

import pytest

PANEL = Path(__file__).resolve().parents[2] / "a0-applicant/webui/tracker.html"


@pytest.fixture(scope="module")
def html() -> str:
    return PANEL.read_text(encoding="utf-8")


class TestTrackerPanel:
    """Source-level assertions for the tracker panel."""

    def test_list_campaigns_via_callJsonApi(self, html):
        assert 'callJsonApi("campaigns", { action: "list" }' in html

    def test_board_via_callJsonApi(self, html):
        assert 'callJsonApi("tracker", { action: "board"' in html

    def test_attention_via_callJsonApi(self, html):
        assert 'callJsonApi("tracker", { action: "attention"' in html

    def test_renders_board_applications(self, html):
        assert "boardApplications" in html

    def test_renders_attention_items(self, html):
        assert "attentionItems" in html

    def test_has_error_line(self, html):
        assert "fatalError" in html

    def test_empty_board(self, html):
        assert "No applications yet" in html

    def test_empty_attention(self, html):
        assert "Nothing needs attention" in html
