"""AZ2 (#837) — the documents panel contract (source assertions).

The panel is browser-rendered HTML/JS (full E2E belongs in the P0-6 Playwright harness),
so here we pin the load-bearing contract at the source level, like the repo's other JS gates.
"""
from __future__ import annotations
from pathlib import Path

import pytest

PANEL = Path(__file__).resolve().parents[2] / "a0-applicant/webui/documents.html"


@pytest.fixture(scope="module")
def html() -> str:
    return PANEL.read_text(encoding="utf-8")


class TestDocumentsPanel:
    """Source-level assertions for the documents panel."""

    def test_list_campaigns_via_callJsonApi(self, html):
        assert 'callJsonApi("campaigns", { action: "list" }' in html

    def test_tracker_board_via_callJsonApi(self, html):
        assert 'callJsonApi("tracker", { action: "board"' in html

    def test_document_list_via_callJsonApi(self, html):
        assert 'callJsonApi("documents", { action: "list"' in html

    def test_approve_via_callJsonApi(self, html):
        assert 'action: "approve"' in html

    def test_decline_via_callJsonApi(self, html):
        assert 'action: "decline"' in html

    def test_provenance_via_callJsonApi(self, html):
        assert 'action: "provenance"' in html

    def test_snapshot_via_callJsonApi(self, html):
        assert 'action: "snapshot"' in html

    def test_degraded_warning(self, html):
        assert "degraded" in html

    def test_fatalError_line(self, html):
        assert "fatalError" in html

    def test_empty_state_no_campaigns(self, html):
        assert "No campaigns" in html or "Select a campaign" in html

    def test_redline_submit_via_callJsonApi(self, html):
        assert 'action: "redline"' in html

    def test_redline_result_render_element(self, html):
        assert 'redlineResults' in html and 'rendered_html' in html

    def test_redline_approve_decline_affordances(self, html):
        assert 'approveRedlineViaDoc' in html and 'dismissRedline' in html
