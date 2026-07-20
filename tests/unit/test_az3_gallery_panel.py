"""AZ3 (#840) — the gallery panel contract (source assertions).

The panel is browser-rendered HTML/JS (full E2E belongs in the P0-6 Playwright harness),
so here we pin the load-bearing contract at the source level, like the repo's other JS gates.
"""
from __future__ import annotations
from pathlib import Path

import pytest

PANEL = Path(__file__).resolve().parents[2] / "a0-applicant/webui/gallery.html"


@pytest.fixture(scope="module")
def html() -> str:
    return PANEL.read_text(encoding="utf-8")


class TestGalleryPanel:
    """Source-level assertions for the gallery panel."""

    def test_list_campaigns_via_callJsonApi(self, html):
        assert 'callJsonApi("campaigns", { action: "list" }' in html

    def test_view_gallery_via_callJsonApi(self, html):
        assert 'callJsonApi("gallery", { action: "view", campaign_id:' in html

    def test_renders_screenshots_collection(self, html):
        assert "galleryData.screenshots" in html

    def test_renders_materials_collection(self, html):
        assert "galleryData.materials" in html

    def test_has_error_line(self, html):
        assert "fatalError" in html

    def test_no_screenshots_empty_state(self, html):
        assert "No screenshots" in html

    def test_no_materials_empty_state(self, html):
        assert "No materials" in html
