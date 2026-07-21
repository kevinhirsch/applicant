"""AZ3 (#839) — the tiers panel contract (source assertions).

The panel is browser-rendered HTML/JS (full E2E belongs in the P0-6 Playwright harness),
so here we pin the load-bearing contract at the source level, like the repo's other JS gates.
"""
from __future__ import annotations
from pathlib import Path

import pytest

PANEL = Path(__file__).resolve().parents[2] / "a0-applicant/webui/tiers.html"


@pytest.fixture(scope="module")
def html() -> str:
    return PANEL.read_text(encoding="utf-8")


class TestTiersPanel:
    """Source-level assertions for the tiers panel."""

    def test_get_tiers_via_callJsonApi(self, html):
        assert "callJsonApi('tiers', " in html
        assert "action: 'get'" in html

    def test_set_tiers_via_callJsonApi(self, html):
        assert "callJsonApi('tiers', " in html
        assert "action: 'set'" in html

    def test_has_instructions(self, html):
        assert "ladder decides which model" in html

    def test_has_error_line(self, html):
        assert "error" in html

    def test_renders_tiers(self, html):
        assert "tiers" in html
        assert "Tier " in html

    def test_empty_state(self, html):
        assert "No tiers configured" in html

    def test_has_save_button(self, html):
        assert "Save ladder" in html

    def test_has_add_tier_button(self, html):
        assert "Add tier" in html
