"""AZ3 (#842) — save-a-job panel contract (source assertions).

The panel is browser-rendered HTML/JS (full E2E belongs in the Playwright harness),
so here we pin the load-bearing contract at the source level, like the repo's other JS gates.
"""
from __future__ import annotations
from pathlib import Path

import pytest

PANEL = Path(__file__).resolve().parents[2] / "a0-applicant/webui/savejob.html"


@pytest.fixture(scope="module")
def html() -> str:
    return PANEL.read_text(encoding="utf-8")


class TestSaveJobPanel:
    """Source-level assertions for the save-a-job panel."""

    def test_save_via_callJsonApi(self, html):
        assert "callJsonApi('savejob'," in html
        assert "action: 'save'" in html

    def test_has_campaign_picker(self, html):
        assert "campaign" in html
        assert "campaign_id" in html

    def test_has_url_input(self, html):
        assert "url" in html
        assert "placeholder" in html

    def test_has_instructions(self, html):
        assert "Paste" in html

    def test_has_error_line(self, html):
        assert "error" in html

    def test_has_save_button(self, html):
        assert "Save job" in html

    def test_has_empty_state(self, html):
        assert "No campaigns" in html
