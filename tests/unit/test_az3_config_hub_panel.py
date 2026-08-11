"""AZ3 (#839) — the config settings hub panel contract (source assertions).

The panel is browser-rendered HTML/JS (full E2E belongs in the P0-6 Playwright harness),
so here we pin the load-bearing contract at the source level, like the repo's other JS gates.
"""
from __future__ import annotations
from pathlib import Path

import pytest

PANEL = Path(__file__).resolve().parents[2] / "a0-applicant/webui/config.html"


@pytest.fixture(scope="module")
def html() -> str:
    return PANEL.read_text(encoding="utf-8")


class TestConfigHubPanel:
    """Source-level assertions for the config settings hub panel."""

    def test_has_title(self, html):
        assert "Settings" in html

    def test_not_empty(self, html):
        """Must have real content beyond just the CSS link."""
        assert len(html) > 200, "config.html is still a near-empty stub"

    def test_has_theme_css(self, html):
        assert "applicant-theme.css" in html

    def test_links_to_channels(self, html):
        assert "window.openModal('/plugins/applicant/webui/channels.html')" in html

    def test_links_to_tiers(self, html):
        assert "window.openModal('/plugins/applicant/webui/tiers.html')" in html

    def test_links_to_privacy(self, html):
        assert "window.openModal('/plugins/applicant/webui/privacy.html')" in html

    def test_links_to_automation(self, html):
        assert "window.openModal('/plugins/applicant/webui/automation.html')" in html

    def test_has_help_affordance(self, html):
        assert "help.html?surface=config" in html

    def test_has_subtitle(self, html):
        assert "Configure" in html or "preferences" in html.lower()

    def test_has_card_elements(self, html):
        assert "card" in html
