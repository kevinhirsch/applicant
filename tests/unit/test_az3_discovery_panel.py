"""AZ3 (#844) — the discovery panel contract (source assertions).

The panel is browser-rendered HTML/JS (full E2E belongs in the P0-6 Playwright harness),
so here we pin the load-bearing contract at the source level, like the repo's other JS gates.
"""
from __future__ import annotations
from pathlib import Path

import pytest

PANEL = Path(__file__).resolve().parents[2] / "a0-applicant/webui/discovery.html"


@pytest.fixture(scope="module")
def html() -> str:
    return PANEL.read_text(encoding="utf-8")


class TestDiscoveryPanel:
    """Source-level assertions for the discovery panel."""

    def test_list_campaigns_via_callJsonApi(self, html):
        assert 'callJsonApi("campaigns", { action: "list" }' in html

    def test_list_sources_via_callJsonApi(self, html):
        assert 'callJsonApi("discovery", { action: "list"' in html

    def test_set_source_via_callJsonApi(self, html):
        assert 'callJsonApi("discovery", { action: "set"' in html

    def test_has_error_line(self, html):
        assert "fatalError" in html

    def test_empty_sources(self, html):
        assert "No discovery sources" in html
