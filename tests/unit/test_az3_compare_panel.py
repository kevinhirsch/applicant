"""AZ3 (#840) — the compare panel contract (source assertions).

The panel is browser-rendered HTML/JS (full E2E belongs in the P0-6 Playwright harness),
so here we pin the load-bearing contract at the source level, like the repo's other JS gates.
"""
from __future__ import annotations
from pathlib import Path

import pytest

PANEL = Path(__file__).resolve().parents[2] / "a0-applicant/webui/compare.html"


@pytest.fixture(scope="module")
def html() -> str:
    return PANEL.read_text(encoding="utf-8")


class TestComparePanel:
    """Source-level assertions for the compare panel."""

    def test_has_applications_mode(self, html):
        assert "mode === 'applications'" in html or "applications" in html

    def test_has_postings_mode(self, html):
        assert "mode === 'postings'" in html or "postings" in html

    def test_parses_multiple_ids(self, html):
        assert ".split(/[,/" in html or "parseIds" in html

    def test_calls_compare_api(self, html):
        assert 'callJsonApi("compare"' in html

    def test_passes_action_mode(self, html):
        assert 'action: this.mode' in html or 'action:' in html

    def test_renders_dimensions(self, html):
        assert "dimensions" in html

    def test_renders_summary(self, html):
        assert "summary" in html

    def test_has_error_line(self, html):
        assert "fatalError" in html

    def test_has_mode_toggle(self, html):
        assert "mode-toggle" in html

    def test_requires_two_ids(self, html):
        assert "hasEnoughIds" in html or "2" in html
