"""AZ3 (#842) — the feedback panel contract (source assertions).

The panel is browser-rendered HTML/JS (full E2E belongs in the P0-6 Playwright harness),
so here we pin the load-bearing contract at the source level, like the repo's other JS gates.
"""
from __future__ import annotations
from pathlib import Path

import pytest

PANEL = Path(__file__).resolve().parents[2] / "a0-applicant/webui/feedback.html"


@pytest.fixture(scope="module")
def html() -> str:
    return PANEL.read_text(encoding="utf-8")


class TestFeedbackPanel:
    """Source-level assertions for the feedback panel."""

    def test_list_campaigns_via_callJsonApi(self, html):
        assert 'callJsonApi("campaigns", { action: "list" }' in html

    def test_history_via_callJsonApi(self, html):
        assert 'callJsonApi("feedback", { action: "history"' in html

    def test_freetext_via_callJsonApi(self, html):
        assert 'callJsonApi("feedback"' in html
        assert 'action: "freetext"' in html

    def test_survey_via_callJsonApi(self, html):
        assert 'callJsonApi("feedback"' in html
        assert 'action: "survey"' in html

    def test_has_error_line(self, html):
        assert "fatalError" in html

    def test_empty_state(self, html):
        assert "No feedback yet" in html
