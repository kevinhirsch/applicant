"""AZ2 (#D3-D4) — the digest panel contract (source assertions).

The panel is browser-rendered HTML/JS (full E2E belongs in the P0-6 Playwright harness),
so here we pin the load-bearing contract at the source level, like the repo's other JS gates.
"""
from pathlib import Path

import pytest

PANEL = Path(__file__).resolve().parents[2] / "a0-applicant/webui/digest.html"


@pytest.fixture(scope="module")
def html() -> str:
    return PANEL.read_text(encoding="utf-8")


class TestDigestPanel:
    """Source-level assertions for the digest panel."""

    def test_drives_the_engine_through_digest_proxy(self, html):
        assert 'callJsonApi("digest", {' in html and 'action: "get"' in html

    def test_approve_button_wired(self, html):
        assert 'action: "approve"' in html and 'application_id:' in html

    def test_decline_button_with_reason_wired(self, html):
        assert 'action: "decline"' in html and 'application_id:' in html and 'reason' in html

    def test_non_blank_reason_enforced(self, html):
        assert '.trim()' in html or '!reason' in html or '!declineReasons' in html

    def test_recap_button_wired(self, html):
        assert 'action: "recap"' in html

    def test_empty_state_present(self, html):
        assert 'empty' in html.lower() or 'no roles' in html.lower()

    def test_error_line_present(self, html):
        assert 'fatalError' in html or 'r.ok' in html or 'r.error' in html
