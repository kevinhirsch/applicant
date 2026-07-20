"""AZ2 (#842) — the easy-apply panel contract (source assertions).

The panel is browser-rendered HTML/JS (full E2E belongs in the P0-6 Playwright harness),
so here we pin the load-bearing contract at the source level, like the repo's other JS gates.
"""
from pathlib import Path

import pytest

PANEL = Path(__file__).resolve().parents[2] / "a0-applicant/webui/easy_apply.html"


@pytest.fixture(scope="module")
def html() -> str:
    return PANEL.read_text(encoding="utf-8")


class TestEasyApplyPanel:
    """Source-level assertions for the easy-apply panel."""

    def test_drives_the_engine_through_easy_apply_proxy(self, html):
        assert 'callJsonApi("easy_apply", {' in html and 'action: "status"' in html

    def test_campaign_picker_present(self, html):
        assert 'callJsonApi("campaigns",' in html and 'action: "list"' in html

    def test_posting_id_input_present(self, html):
        assert 'postingId' in html or 'posting_id' in html

    def test_empty_state_present(self, html):
        assert 'No easy-apply data yet' in html or 'empty' in html.lower()

    def test_error_line_present(self, html):
        assert 'fatalError' in html or "Couldn't reach the easy-apply engine" in html
