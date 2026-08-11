"""AZ3 (#839) — the automation panel contract (source assertions).

The panel is browser-rendered HTML/JS (full E2E belongs in the P0-6 Playwright harness),
so here we pin the load-bearing contract at the source level, like the repo's other JS gates.
"""
from __future__ import annotations
from pathlib import Path

import pytest

PANEL = Path(__file__).resolve().parents[2] / "a0-applicant/webui/automation.html"


@pytest.fixture(scope="module")
def html() -> str:
    return PANEL.read_text(encoding="utf-8")


class TestAutomationPanel:
    """Source-level assertions for the automation preferences panel."""

    def test_init_loads_prefs(self, html):
        assert "callJsonApi('automation'," in html
        assert "action: 'get'" in html

    def test_save_calls_set(self, html):
        assert "callJsonApi('automation'," in html
        assert "action: 'set'" in html

    def test_has_error_line(self, html):
        assert "error" in html

    def test_has_loading_state(self, html):
        assert "loading" in html

    def test_has_approval_fields(self, html):
        assert "approval_timeout_days" in html or "approval_wait_seconds" in html

    def test_has_scheduler_field(self, html):
        assert "scheduler_interval_seconds" in html

    def test_has_ats_floor(self, html):
        assert "ats_match_rate_floor" in html

    def test_has_memory_fields(self, html):
        assert "memory_max_chars" in html

    def test_has_browser_fields(self, html):
        assert "browser_engine" in html

    def test_has_help_affordance(self, html):
        assert "help-btn" in html
        assert "help.html?surface=automation" in html

    def test_has_header_title(self, html):
        assert "Automation" in html
