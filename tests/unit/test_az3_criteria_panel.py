"""AZ3 (#840) — the criteria panel contract (source assertions).

The panel is browser-rendered HTML/JS (full E2E belongs in the P0-6 Playwright harness),
so here we pin the load-bearing contract at the source level, like the repo's other JS gates.
"""
from __future__ import annotations
from pathlib import Path

import pytest

PANEL = Path(__file__).resolve().parents[2] / "a0-applicant/webui/criteria.html"


@pytest.fixture(scope="module")
def html() -> str:
    return PANEL.read_text(encoding="utf-8")


class TestCriteriaPanel:
    """Source-level assertions for the criteria panel."""

    def test_list_campaigns_via_callJsonApi(self, html):
        assert 'callJsonApi("campaigns", { action: "list" }' in html

    def test_view_criteria_via_callJsonApi(self, html):
        assert 'callJsonApi("criteria", { action: "view", campaign_id:' in html

    def test_signature_via_callJsonApi(self, html):
        assert 'callJsonApi("criteria", { action: "signature", campaign_id:' in html

    def test_apply_learned_via_callJsonApi(self, html):
        assert 'action: "apply_learned"' in html

    def test_has_error_line(self, html):
        assert "fatalError" in html

    def test_empty_campaigns(self, html):
        assert "No campaigns" in html

    def test_empty_signature(self, html):
        assert "No converting-role signature data yet" in html
