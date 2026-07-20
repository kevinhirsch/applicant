"""AZ3 (#839) — the fonts panel contract (source assertions).

The panel is browser-rendered HTML/JS (full E2E belongs in the P0-6 Playwright harness),
so here we pin the load-bearing contract at the source level, like the repo's other JS gates.
"""
from __future__ import annotations
from pathlib import Path

import pytest

PANEL = Path(__file__).resolve().parents[2] / "a0-applicant/webui/fonts.html"


@pytest.fixture(scope="module")
def html() -> str:
    return PANEL.read_text(encoding="utf-8")


class TestFontsPanel:
    """Source-level assertions for the fonts panel."""

    def test_list_fonts_via_callJsonApi(self, html):
        assert "callJsonApi('fonts', " in html
        assert "action: 'list'" in html

    def test_detect_fonts_via_callJsonApi(self, html):
        assert "callJsonApi('fonts', " in html
        assert "action: 'detect'" in html

    def test_install_font_via_callJsonApi(self, html):
        assert "callJsonApi('fonts'," in html
        assert "action: 'install'" in html

    def test_renders_installed_fonts(self, html):
        assert "fonts" in html
        assert "installed" in html

    def test_has_error_line(self, html):
        assert "error" in html

    def test_no_fonts_empty_state(self, html):
        assert "No fonts installed" in html

    def test_has_detect_button(self, html):
        assert "Detect fonts" in html

    def test_has_install_section(self, html):
        assert "Install font" in html
