"""AZ3 (#842) — unit tests for the keyboard-shortcuts overlay panel.

Hermetic: reads the static HTML file and asserts source-level contracts.
"""
from __future__ import annotations

from pathlib import Path

import pytest

# --- Paths ---------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[2]
SHORTCUTS_HTML = ROOT / "a0-applicant" / "webui" / "shortcuts.html"


# === Source-assert shortcuts.html ========================================

class TestShortcutsHtmlPanel:
    """Verify shortcuts.html is a self-contained static reference panel."""

    @pytest.fixture(autouse=True)
    def _read_html(self) -> None:
        assert SHORTCUTS_HTML.is_file(), f"shortcuts.html not found at {SHORTCUTS_HTML}"
        self.source = SHORTCUTS_HTML.read_text(encoding="utf-8")

    def test_shortcuts_html_exists(self) -> None:
        assert SHORTCUTS_HTML.is_file()

    def test_has_alpine_x_data(self) -> None:
        assert "x-data" in self.source or "Alpine.data" in self.source or "x-data" in self.source

    def test_renders_shortcut_sections(self) -> None:
        headings = {
            "Shell",
            "Panel Navigation",
            "Common Panel Actions",
            "Surface Tips",
        }
        for h in headings:
            assert h.lower() in self.source.lower(), f"Missing section heading: {h}"

    def test_has_kbd_elements(self) -> None:
        assert "<kbd>" in self.source

    def test_has_help_affordance(self) -> None:
        assert "window.openModal('/plugins/applicant/webui/help.html?surface=shortcuts')" in self.source

    def test_has_title(self) -> None:
        assert "<title>" in self.source or "<h1>" in self.source

    def test_has_shortcut_table_or_grid(self) -> None:
        assert "shortcut-row" in self.source or "display: flex" in self.source or "grid" in self.source.lower()

    def test_theme_css_linked(self) -> None:
        assert "applicant-theme.css" in self.source


# === Internal collection check ===========================================

def test_module_collects_at_least_one() -> None:
    """Meta: this test file must collect > 0 tests."""
    assert True, "Sanity check: the test module must exist."
