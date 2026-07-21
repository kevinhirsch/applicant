"""AZ3 (#842) Slice B — unit tests for the demo-data panel HTML.

Hermetic: source-asserts the panel contains the required UI elements.
"""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DEMO_HTML = ROOT / "a0-applicant" / "webui" / "demo.html"


class TestDemoHtmlPanel:
    """Verify demo.html panel structure and content."""

    def test_demo_html_exists(self) -> None:
        assert DEMO_HTML.is_file(), f"demo.html not found at {DEMO_HTML}"

    def test_calls_status_on_init(self) -> None:
        source = DEMO_HTML.read_text(encoding="utf-8")
        # Must call callJsonApi('demo', {action: 'status'}) on init
        assert "callJsonApi('demo'" in source or 'callJsonApi("demo"' in source
        assert "action: 'status'" in source or 'action: "status"' in source
        assert "loadStatus" in source

    def test_has_seed_button(self) -> None:
        source = DEMO_HTML.read_text(encoding="utf-8")
        assert "Load demo data" in source
        assert "seedData" in source or "seed" in source.lower()

    def test_has_clear_button(self) -> None:
        source = DEMO_HTML.read_text(encoding="utf-8")
        assert "Clear demo data" in source
        assert "clearData" in source or "clear" in source.lower()

    def test_demo_off_state(self) -> None:
        source = DEMO_HTML.read_text(encoding="utf-8")
        assert "Demo mode is disabled" in source
        assert "DEMO_MODE=1" in source

    def test_has_loading_state(self) -> None:
        source = DEMO_HTML.read_text(encoding="utf-8")
        assert "loading" in source.lower()

    def test_has_error_line(self) -> None:
        source = DEMO_HTML.read_text(encoding="utf-8")
        assert "error" in source.lower()
        assert "x-show=\"error" in source or 'x-show="error' in source

    def test_has_help_affordance(self) -> None:
        source = DEMO_HTML.read_text(encoding="utf-8")
        assert "help-btn" in source
        assert "help.html?surface=demo" in source

    def test_has_alpine_data(self) -> None:
        source = DEMO_HTML.read_text(encoding="utf-8")
        assert "x-data" in source
        assert "ademo" in source

    def test_demo_mode_gating_copy(self) -> None:
        source = DEMO_HTML.read_text(encoding="utf-8")
        assert "Demo data is separate" in source or "separate from real data" in source


def test_module_collects_at_least_one() -> None:
    """Meta: this test file must collect > 0 tests."""
    assert True
