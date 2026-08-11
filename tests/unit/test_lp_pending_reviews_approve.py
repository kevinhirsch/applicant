"""Landing "Pending Reviews" Approve button — P1 fix.

``lpPendingReviews.approve(g)`` (the Today landing page's hero gadget) used to call
ONLY ``resolve_bulk`` (``pending_actions.resolved = true``) — it never touched the
application's generated materials at all, so it looked identical to just dismissing
the card. The fix routes through the SAME review-gate decision the Review & Refine
modal's "Continue" button uses (``POST /api/review/{id}/continue`` via the review
proxy's ``decide``/``continue`` action) to actually approve the application's
materials BEFORE dismissing the card, and only dismisses on success.

The panel is browser-rendered HTML/Alpine (full E2E belongs in the P0-6 Playwright
harness), so — like the repo's other JS gates (``test_az2_digest_panel.py`` /
``test_rux_review_panel.py``) — this pins the load-bearing contract at the source
level, extracting the ``approve(g)`` method body so ordering (continue BEFORE
dismiss; bail out on failure) can be asserted directly.
"""
from __future__ import annotations

from pathlib import Path

import pytest

PANEL = (
    Path(__file__).resolve().parents[2]
    / "a0-webui/components/welcome/welcome-screen.html"
)


@pytest.fixture(scope="module")
def html() -> str:
    return PANEL.read_text(encoding="utf-8")


def _approve_body(html: str) -> str:
    start = html.index("async approve(g) {")
    end = html.index("async snooze(g) {")
    assert start < end
    return html[start:end]


class TestApproveActuallyApprovesMaterials:
    def test_approve_method_exists(self, html):
        assert "async approve(g) {" in html

    def test_approve_decides_continue_through_the_review_gate(self, html):
        body = _approve_body(html)
        assert 'callJsonApi("review"' in body
        assert 'action: "decide"' in body
        assert 'decision: "continue"' in body
        assert "application_id: g.applicationId" in body

    def test_continue_is_called_before_dismissing_the_card(self, html):
        body = _approve_body(html)
        idx_decide = body.index('action: "decide"')
        idx_resolve = body.index('action: "resolve_bulk"')
        assert idx_decide < idx_resolve, "materials must be approved BEFORE the card is dismissed"

    def test_still_dismisses_the_card_on_success(self, html):
        body = _approve_body(html)
        assert 'action: "resolve_bulk"' in body
        assert "action_ids: g.items.map" in body
        assert "await this.load();" in body

    def test_bails_out_before_dismissing_on_materials_approval_failure(self, html):
        # A failed continue must `return` before ever reaching resolve_bulk -- never
        # silently dismiss a pending review whose materials failed to approve.
        body = _approve_body(html)
        idx_check = body.index("!r || !r.ok")
        idx_return = body.index("return;", idx_check)
        idx_resolve = body.index('action: "resolve_bulk"')
        assert idx_check < idx_return < idx_resolve

    def test_surfaces_a_per_group_error_on_failure(self, html):
        body = _approve_body(html)
        assert "g.error" in body

    def test_old_dismiss_only_behavior_is_gone(self, html):
        # Old bug: approve() called resolve_bulk as its ONLY side effect -- nothing
        # ever approved the application's materials.
        body = _approve_body(html)
        assert 'callJsonApi("review"' in body, "must route through the review gate, not just dismiss"


class TestPerGroupErrorState:
    def test_groups_seed_an_error_field(self, html):
        assert 'error: ""' in html

    def test_error_rendered_in_the_review_row(self, html):
        assert 'x-show="g.error"' in html
        assert 'x-text="g.error"' in html
