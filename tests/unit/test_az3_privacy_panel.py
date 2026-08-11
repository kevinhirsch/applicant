"""AZ3 (#839) — the privacy panel contract (source assertions).

The panel is browser-rendered HTML/JS (full E2E belongs in the P0-6 Playwright harness),
so here we pin the load-bearing contract at the source level, like the repo's other JS gates.
"""
from __future__ import annotations
from pathlib import Path

import pytest

PANEL = Path(__file__).resolve().parents[2] / "a0-applicant/webui/privacy.html"


@pytest.fixture(scope="module")
def html() -> str:
    return PANEL.read_text(encoding="utf-8")


class TestPrivacyPanel:
    """Source-level assertions for the privacy & sandbox panel."""

    def test_get_via_callJsonApi(self, html):
        assert "callJsonApi('privacy', {" in html
        assert "action: 'get'" in html

    def test_set_telemetry_via_callJsonApi(self, html):
        assert "callJsonApi('privacy'," in html
        assert "action: 'set_telemetry'" in html

    def test_set_sandbox_via_callJsonApi(self, html):
        assert "callJsonApi('privacy'," in html
        assert "action: 'set_sandbox'" in html

    def test_telemetry_off_copy(self, html):
        assert "telemetry is off" in html.lower()

    def test_has_instructions(self, html):
        assert "instructions" in html

    def test_has_error_line(self, html):
        assert "error" in html

    def test_has_sandbox_fields(self, html):
        assert "proxmox_api_url" in html

    def test_has_privacy_label(self, html):
        assert "Privacy" in html
