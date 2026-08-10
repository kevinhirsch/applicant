"""EPIC REVIEW-UX (RUX-1/2/3/5) — the Review modal panel contract (source assertions).

The panel is browser-rendered HTML/Alpine (full E2E belongs in the P0-6 Playwright
harness), so — like the repo's other JS gates (see ``test_az2_digest_panel.py`` /
``test_az2_update_panel.py``) — we pin the load-bearing contract at the source level.

The Review modal is the existing ``documents.html`` panel (the surface the Digest
"Review" button opens); the RUX decision + refinement workflow is folded into it
reuse-first rather than forking a new panel. It is a THIN UX layer over the engine's
``/api/review`` surface (proxied at ``plugins/applicant/review``); these assertions pin
the wire contract the frontend depends on so the rux-backend router and the Integrate
step can align.
"""
from pathlib import Path

import pytest

PANEL = Path(__file__).resolve().parents[2] / "a0-applicant/webui/documents.html"


@pytest.fixture(scope="module")
def html() -> str:
    return PANEL.read_text(encoding="utf-8")


class TestReviewModalExists:
    def test_panel_file_exists(self):
        assert PANEL.is_file(), f"Review modal not found at {PANEL}"

    def test_links_shared_stylesheet(self, html):
        # UIKIT recipe step 2: link the shared theme stylesheet like every panel.
        assert '/plugins/applicant/webui/applicant-theme.css' in html

    def test_scoped_panel_class(self, html):
        # UIKIT recipe step 3: scope styles under one .aXXX panel class.
        assert 'adoc' in html

    def test_help_button_convention(self, html):
        assert 'help-btn' in html


class TestReviewWireContract:
    def test_drives_engine_through_review_proxy(self, html):
        assert 'callJsonApi("review",' in html

    def test_loads_review_payload_on_init(self, html):
        assert 'action: "get"' in html


class TestSourcePostingLink:
    """RUX-1: prominent 'View source posting' link + freshness + cached snapshot."""

    def test_source_posting_link_present(self, html):
        assert 'source_url' in html
        assert 'View source posting' in html or 'View source' in html

    def test_source_link_opens_new_tab_safely(self, html):
        assert 'target="_blank"' in html
        assert 'noopener' in html  # rel="noopener noreferrer" — no window.opener leak

    def test_source_link_guarded_against_non_http(self, html):
        # Defense in depth: never render a javascript:/data: URL as a live link.
        assert 'http' in html and ('startsWith' in html or 'startswith' in html.lower())

    def test_posted_freshness_cue(self, html):
        assert 'posted_relative' in html
        assert 'posted_stale' in html

    def test_cached_snapshot_fallback(self, html):
        assert 'action: "snapshot"' in html
        assert 'snapshot' in html.lower()


class TestThreeWayDecision:
    """RUX-2: Continue / Save-for-later / Discard-with-reason."""

    def test_decision_action_wired(self, html):
        assert 'action: "decide"' in html or 'action: "decision"' in html

    def test_continue_option(self, html):
        assert 'continue' in html.lower() and 'Continue' in html

    def test_save_for_later_option(self, html):
        assert 'save' in html.lower() and ('Save for later' in html or 'Save-for-later' in html or 'Save for Later' in html)

    def test_discard_requires_reason(self, html):
        assert 'discard' in html.lower() and 'Discard' in html
        # Discard opens a reason prompt and a blank reason is rejected.
        assert 'reason' in html
        assert '.trim()' in html


class TestPerSectionReview:
    """RUX-3: inline edit, regenerate section, apply across sections, regenerate all."""

    def test_renders_sections(self, html):
        assert 'sections' in html
        assert 'section_id' in html

    def test_inline_edit_save(self, html):
        assert 'action: "edit_section"' in html
        assert 'content' in html
        assert 'textarea' in html  # inline editable text

    def test_regenerate_single_section(self, html):
        assert 'action: "regenerate_section"' in html

    def test_apply_feedback_across_sections(self, html):
        assert 'action: "apply_feedback"' in html

    def test_regenerate_whole_app(self, html):
        assert 'action: "regenerate_all"' in html

    def test_review_gated_status_surfaced(self, html):
        # Edits/regens stay review-gated — the section status must be shown.
        assert 'status' in html


class TestFreeformProfileFeedback:
    """RUX-5: per-app freeform feedback → global profile, transparent + reversible."""

    def test_profile_feedback_box(self, html):
        assert 'action: "profile_feedback"' in html

    def test_shows_what_changed(self, html):
        assert 'changes' in html

    def test_revertable(self, html):
        assert 'action: "revert_feedback"' in html or 'revert' in html.lower()


class TestStatesAndTheming:
    def test_loading_state(self, html):
        assert 'loading' in html.lower() and 'spinner' in html.lower()

    def test_error_line(self, html):
        assert 'fatalError' in html

    def test_theme_tokens_used(self, html):
        # Must theme via existing CSS custom properties, not raw hardcoded colors.
        assert 'var(--color-text' in html
        assert 'var(--color-background' in html or 'var(--color-panel' in html

    def test_no_whiteonwhite_input_bg_trap(self, html):
        # UIKIT §1 live gap: --color-input-bg is a single :root literal (#fff) that is
        # invisible-on-white in dark mode. Cards/surfaces must not lean on it.
        assert 'var(--color-input-bg' not in html
