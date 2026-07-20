"""WT (#w1) — the dormant panel contract (source assertions).

The panel is browser-rendered HTML/JS (full E2E belongs in the P0-6 Playwright harness),
so here we pin the load-bearing contract at the source level, like the repo's other JS gates.
"""
from pathlib import Path

import pytest

PANEL = Path(__file__).resolve().parents[2] / "a0-applicant/webui/dormant.html"


@pytest.fixture(scope="module")
def html() -> str:
    return PANEL.read_text(encoding="utf-8")


class TestDormantPanel:
    """Source-level assertions for the dormant panel."""

    def test_drives_through_dormant_proxy(self, html):
        assert 'callJsonApi("dormant", {' in html and 'action: "list"' in html

    def test_badge_styles_present(self, html):
        assert 'badge' in html and 'class="badge"' in html
        assert 'badge.live' in html and 'badge.dormant' in html

    def test_surface_fields_rendered(self, html):
        assert 's.key' in html and 's.name' in html and 's.status' in html and 's.live_phase' in html

    def test_empty_state_present(self, html):
        assert 'No dormant surfaces' in html

    def test_error_line_present(self, html):
        assert 'fatalError' in html
        assert "Couldn't reach the dormant surfaces" in html or "Couldn\\'t reach the dormant surfaces" in html

    def test_alpine_data_wired(self, html):
        assert 'x-data="dormantPanel()"' in html and 'Alpine.data("dormantPanel"' in html
