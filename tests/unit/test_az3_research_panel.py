"""AZ3 (#842) — the research panel contract (source assertions).

The panel is browser-rendered HTML/JS (full E2E belongs in the P0-6 Playwright harness),
so here we pin the load-bearing contract at the source level, like the repo's other JS gates.
"""
from __future__ import annotations
from pathlib import Path

import pytest

PANEL = Path(__file__).resolve().parents[2] / "a0-applicant/webui/research.html"


@pytest.fixture(scope="module")
def html() -> str:
    return PANEL.read_text(encoding="utf-8")


class TestResearchPanel:
    """Source-level assertions for the research panel."""

    def test_list_campaigns_via_callJsonApi(self, html):
        assert 'callJsonApi("campaigns", { action: "list" }' in html

    def test_cached_via_callJsonApi(self, html):
        assert 'callJsonApi("research", { action: "cached"' in html

    def test_budget_via_callJsonApi(self, html):
        assert 'callJsonApi("research", { action: "budget"' in html

    def test_run_via_callJsonApi(self, html):
        assert 'callJsonApi("research"' in html
        assert 'action: "run"' in html

    def test_has_error_line(self, html):
        assert "fatalError" in html

    def test_empty_cached(self, html):
        assert "No cached results" in html

    def test_empty_budget(self, html):
        assert "No budget data" in html
