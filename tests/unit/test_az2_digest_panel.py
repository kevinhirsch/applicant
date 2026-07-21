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

    def test_source_shortfalls_read_and_rendered(self, html):
        """Panel reads source_shortfalls from API response and renders a per-item block."""
        assert "sourceShortfalls" in html, "Alpine state sourceShortfalls must be declared"
        assert "source_shortfalls" in html, "API response field source_shortfalls must be read"
        assert "shortfalls" in html.lower(), "Shortfalls must have a render block"
        # Ensure render is NOT conditioned solely on empty rows
        # The block should reference sourceShortfalls.length, not rows.length
        assert "sourceShortfalls.length > 0" in html or "sourceShortfalls.length>0" in html, "Shortfalls render must be gated on sourceShortfalls.length, not rows.length"
        # Assert per-item message rendering
        assert "s.message" in html, "Each shortfall item must render the message field"

    def test_deep_link_to_documents_review(self, html):
        """Each digest row has a deep-link/button into the documents review surface carrying application_id."""
        assert "window.openModal" in html, "Must use shell's openModal convention"
        assert "documents.html" in html, "Must navigate to the documents panel"
        assert "application_id" in html, "Must reference application_id in the deep-link"
        assert "Review" in html, "The deep-link button should be labeled 'Review'"
        # Confirm the link is per-row (in the actions div or with template x-for)
        assert 'x-for="row in rows"' in html, "Must be inside the row template"
