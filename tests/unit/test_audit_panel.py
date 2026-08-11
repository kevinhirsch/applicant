"""AZ2 (#842) — the audit panel contract (source assertions).

The panel is browser-rendered HTML/JS (full E2E belongs in the P0-6 Playwright harness),
so here we pin the load-bearing contract at the source level, like the repo's other JS gates.
"""
from pathlib import Path

import pytest

PANEL = Path(__file__).resolve().parents[2] / "a0-applicant/webui/audit.html"


@pytest.fixture(scope="module")
def html() -> str:
    return PANEL.read_text(encoding="utf-8")


class TestAuditPanel:
    """Source-level assertions for the audit panel."""

    def test_drives_the_engine_through_audit_proxy(self, html):
        assert 'callJsonApi("audit", {' in html and 'action: "log"' in html

    def test_campaign_picker_present(self, html):
        assert 'callJsonApi("campaigns",' in html and 'action: "list"' in html

    def test_empty_state_present(self, html):
        assert 'No audit entries yet' in html

    def test_error_line_present(self, html):
        assert 'fatalError' in html or "Couldn't reach the audit engine" in html
