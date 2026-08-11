"""AZ2 (#842) — the conversion panel contract (source assertions).

The panel is browser-rendered HTML/JS (full E2E belongs in the P0-6 Playwright harness),
so here we pin the load-bearing contract at the source level, like the repo's other JS gates.
"""
from pathlib import Path

import pytest

PANEL = Path(__file__).resolve().parents[2] / "a0-applicant/webui/conversion.html"


@pytest.fixture(scope="module")
def html() -> str:
    return PANEL.read_text(encoding="utf-8")


class TestConversionPanel:
    """Source-level assertions for the conversion panel."""

    def test_drives_the_engine_through_conversion_proxy(self, html):
        assert 'callJsonApi("conversion", {' in html and 'action: "engine"' in html

    def test_preview_wired(self, html):
        assert 'action: "preview"' in html and 'callJsonApi("conversion",' in html

    def test_accept_wired(self, html):
        assert 'action: "accept"' in html and 'callJsonApi("conversion",' in html

    def test_reject_wired(self, html):
        assert 'action: "reject"' in html and 'callJsonApi("conversion",' in html

    def test_campaign_picker_present(self, html):
        assert 'callJsonApi("campaigns",' in html and 'action: "list"' in html

    def test_empty_state_present(self, html):
        assert 'No campaign selected' in html or 'empty' in html.lower()

    def test_error_line_present(self, html):
        assert 'fatalError' in html or "Couldn\\'t reach the conversion engine" in html
