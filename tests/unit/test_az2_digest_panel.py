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

    def test_deep_link_to_review_modal(self, html):
        """Each digest row opens the Review modal (documents.html) carrying the posting
        context via a global handoff (modal panels can't read the modal path's query)."""
        assert "window.openModal" in html, "Must use shell's openModal convention"
        assert "documents.html" in html, "Must navigate to the review modal (documents.html)"
        assert "posting_id" in html, "Must carry the posting_id into the review context"
        assert "__applicantReview" in html, "Must hand the posting context over on the global"
        assert "Review" in html, "The deep-link button should be labeled 'Review'"
        # Confirm the link is per-row (in the actions div or with template x-for)
        assert 'x-for="row in rows"' in html, "Must be inside the row template"

    def test_source_posting_link_on_row(self, html):
        """RUX-1: a prominent 'View source posting' link opens the live listing in a
        new tab, sourced from the row's link/source_url, with opener-leak protection."""
        assert "View source posting" in html or "View source" in html
        assert 'target="_blank"' in html
        assert "noopener" in html
        # Sourced from the digest row payload (build_digest emits row.link = source_url).
        assert "row.link" in html or "source_url" in html

    def test_cached_snapshot_fallback_on_row(self, html):
        """RUX-1: when the source URL is pulled/unreachable, a cached snapshot is offered."""
        assert 'action: "snapshot"' in html
        assert "snapshot" in html.lower()

    def test_posting_feedback_wired(self, html):
        assert 'callJsonApi("feedback",' in html
        assert 'action: "posting"' in html
        assert 'posting_id:' in html and 'sentiment:' in html

    def test_review_never_passes_posting_id_as_application_id(self, html):
        """Bug fix (P1, 404 "no such application"): /api/digest rows are
        pre-application POSTINGS with no application_id (0 of 98 in prod). The old
        `row.application_id || row.posting_id` fallback silently passed a posting id
        off as an application id, 404ing the review surface on every un-drafted row.
        """
        assert "row.application_id || row.posting_id" not in html
        assert "async openReview(row)" in html, "openReview must await the draft call"

    def test_review_drafts_the_application_before_opening_when_undrafted(self, html):
        """An un-drafted row (no application_id yet) must be DRAFTED first -- routed
        through the review proxy's dedicated draft action -- before the review
        surface is ever opened."""
        assert 'action: "draft"' in html
        assert "posting_id: postingId" in html
        # The modal is opened with the RESOLVED application id, never the raw
        # row/posting id.
        assert "encodeURIComponent(applicationId)" in html
        assert "encodeURIComponent(row.posting_id)" not in html

    def test_review_surfaces_a_draft_failure_instead_of_opening_a_broken_modal(self, html):
        assert "reviewError" in html
        assert "reviewBusy" in html
