# -*- coding: utf-8 -*-
"""Computed-contrast regression test for the a0-applicant theme tokens fixed
under the UIKIT-STANDARDS.md contrast audit (docs/UIKIT-STANDARDS.md §1/§2/§6).

Does NOT launch a browser or render anything — it reads the actual hex literals
out of the shipped CSS (``a0-applicant/webui/applicant-theme.css`` and the base
shell's ``agent-zero/webui/index.css``) and runs the standard WCAG 2.1
relative-luminance/contrast-ratio formula against them. This is the executable
proof for the "light-mode leak" class of bug documented in UIKIT-STANDARDS.md
§1: a color token declared once (only at ``:root``, i.e. only for dark, the
shipped default) with no ``.light-mode`` counterpart silently fails contrast
in whichever theme it wasn't tuned for. Parsing the real file (instead of
hand-copying the hex values into the test) means a future edit that
re-introduces a single shared literal, or nudges a value out of AA range,
fails this test instead of shipping unnoticed.

BDD scenarios covered (see the tests below for the Given/When/Then per pair):

    Given the app in dark mode (the shipped default),
    When a user reads a panel's secondary/meta text, a primary button's
      label, or text inside a card/input surface,
    Then the text/background contrast is >= 4.5:1 (WCAG AA, normal text).

    Given the app in light mode (opt-in via the sidebar preferences toggle),
    When a user reads the same three things,
    Then the text/background contrast is >= 4.5:1 (WCAG AA, normal text).

Three token pairs are covered, matching the UIKIT audit's numbered bugs:

    1. ``--color-text-secondary`` (was a single #5a5a5a literal, 2.7:1 on the
       dark background — an AA fail) vs. the backgrounds it actually renders
       against in each theme (page bg, panel bg, and the card/input surface).
    2. ``--ap-btn-primary-bg`` (new token backing white .btn.primary /
       .sidebar-action.active / .help-btn:hover label text; dark mode was
       4.35:1 via the shared --color-primary-dark, an AA borderline fail).
    3. ``--color-input-bg`` (was a single #ffffff literal shared by both
       themes; in dark mode that's a white .card/.item/.surface/input
       background under white --ap-color-text — 1:1, i.e. invisible text).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent.parent

APPLICANT_THEME_CSS = PROJECT_ROOT / "a0-applicant" / "webui" / "applicant-theme.css"
BASE_SHELL_INDEX_CSS = PROJECT_ROOT / "agent-zero" / "webui" / "index.css"

WCAG_AA_NORMAL_TEXT = 4.5


# ---------------------------------------------------------------------------
# WCAG 2.1 relative-luminance / contrast-ratio formula (self-contained — no
# external deps). https://www.w3.org/TR/WCAG21/#contrast-minimum
# ---------------------------------------------------------------------------


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.strip().lstrip("#")
    if len(h) == 8:  # drop alpha channel, e.g. "#444444a8"
        h = h[:6]
    if len(h) == 3:  # expand shorthand, e.g. "#fff"
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _channel_luminance(c: int) -> float:
    c_srgb = c / 255
    if c_srgb <= 0.03928:
        return c_srgb / 12.92
    return ((c_srgb + 0.055) / 1.055) ** 2.4


def relative_luminance(hex_color: str) -> float:
    r, g, b = _hex_to_rgb(hex_color)
    return 0.2126 * _channel_luminance(r) + 0.7152 * _channel_luminance(g) + 0.0722 * _channel_luminance(b)


def contrast_ratio(hex_a: str, hex_b: str) -> float:
    l_a = relative_luminance(hex_a)
    l_b = relative_luminance(hex_b)
    lighter, darker = max(l_a, l_b), min(l_a, l_b)
    return (lighter + 0.05) / (darker + 0.05)


# ---------------------------------------------------------------------------
# Tiny CSS custom-property extractor — reads the real declared hex literal for
# a given `--token-name` out of a stylesheet's text, so the assertions below
# are tied to the shipped source, not a hand-copied snapshot of it.
# ---------------------------------------------------------------------------


def _extract_all(css_text: str, token_name: str) -> list[str]:
    # Exact-name match: the colon must directly follow (mod whitespace), so
    # `--color-text-secondary` won't false-match inside
    # `--color-text-secondary-dark`.
    pattern = re.escape(token_name) + r"\s*:\s*([^;]+);"
    return [m.strip() for m in re.findall(pattern, css_text)]


def _extract_hex(css_text: str, token_name: str, *, occurrence: int = 0) -> str:
    matches = _extract_all(css_text, token_name)
    assert matches, f"token {token_name!r} not found in stylesheet"
    value = matches[occurrence]
    assert re.fullmatch(r"#[0-9a-fA-F]{3,8}", value), (
        f"token {token_name!r} (occurrence {occurrence}) is {value!r}, "
        "not a literal hex color — update the test's extraction logic"
    )
    return value


@pytest.fixture(scope="module")
def applicant_theme_css() -> str:
    return APPLICANT_THEME_CSS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def base_shell_index_css() -> str:
    return BASE_SHELL_INDEX_CSS.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Bug 1 — --color-text-secondary (dark mode: was 2.7:1, now theme-scoped)
# ---------------------------------------------------------------------------


class TestSecondaryTextContrast:
    """Given the app in {dark,light} mode, When a user reads a panel's
    secondary/meta text (.sub/.meta/.role/.why/.empty/.badge/.help-btn —
    all consumers of --color-text-secondary), Then contrast against every
    background that text actually renders on is >= 4.5:1."""

    def test_dark_mode_secondary_text_vs_page_background(self, applicant_theme_css, base_shell_index_css):
        secondary = _extract_hex(applicant_theme_css, "--color-text-secondary-dark")
        page_bg = _extract_hex(base_shell_index_css, "--color-background-dark")
        ratio = contrast_ratio(secondary, page_bg)
        assert ratio >= WCAG_AA_NORMAL_TEXT, (
            f"dark-mode --color-text-secondary ({secondary}) vs page bg ({page_bg}) "
            f"= {ratio:.2f}:1, below WCAG AA {WCAG_AA_NORMAL_TEXT}:1"
        )

    def test_dark_mode_secondary_text_vs_panel_background(self, applicant_theme_css, base_shell_index_css):
        secondary = _extract_hex(applicant_theme_css, "--color-text-secondary-dark")
        panel_bg = _extract_hex(base_shell_index_css, "--color-panel-dark")
        ratio = contrast_ratio(secondary, panel_bg)
        assert ratio >= WCAG_AA_NORMAL_TEXT, (
            f"dark-mode --color-text-secondary ({secondary}) vs --color-panel-dark ({panel_bg}) "
            f"= {ratio:.2f}:1, below WCAG AA {WCAG_AA_NORMAL_TEXT}:1"
        )

    def test_dark_mode_secondary_text_vs_card_input_surface(self, applicant_theme_css):
        secondary = _extract_hex(applicant_theme_css, "--color-text-secondary-dark")
        card_bg = _extract_hex(applicant_theme_css, "--color-input-bg-dark")
        ratio = contrast_ratio(secondary, card_bg)
        assert ratio >= WCAG_AA_NORMAL_TEXT, (
            f"dark-mode --color-text-secondary ({secondary}) vs --color-input-bg-dark ({card_bg}) "
            f"= {ratio:.2f}:1, below WCAG AA {WCAG_AA_NORMAL_TEXT}:1"
        )

    def test_light_mode_secondary_text_vs_page_background(self, applicant_theme_css, base_shell_index_css):
        secondary = _extract_hex(applicant_theme_css, "--color-text-secondary-light")
        page_bg = _extract_hex(base_shell_index_css, "--color-background-light")
        ratio = contrast_ratio(secondary, page_bg)
        assert ratio >= WCAG_AA_NORMAL_TEXT, (
            f"light-mode --color-text-secondary ({secondary}) vs page bg ({page_bg}) "
            f"= {ratio:.2f}:1, below WCAG AA {WCAG_AA_NORMAL_TEXT}:1"
        )

    def test_light_mode_secondary_text_vs_card_input_surface(self, applicant_theme_css):
        secondary = _extract_hex(applicant_theme_css, "--color-text-secondary-light")
        card_bg = _extract_hex(applicant_theme_css, "--color-input-bg-light")
        ratio = contrast_ratio(secondary, card_bg)
        assert ratio >= WCAG_AA_NORMAL_TEXT, (
            f"light-mode --color-text-secondary ({secondary}) vs --color-input-bg-light ({card_bg}) "
            f"= {ratio:.2f}:1, below WCAG AA {WCAG_AA_NORMAL_TEXT}:1"
        )

    def test_historical_bug_reproduction_shared_literal_failed_dark_aa(self, base_shell_index_css):
        """Documents *why* the fix was needed: the old single literal
        (#5a5a5a, shared by both themes pre-fix) measured 2.7:1 against the
        dark background — a real AA fail, not a hypothetical one. This test
        has no dependency on the current token split; it stands as a
        permanent record of the red state this change turned green."""
        old_shared_literal = "#5a5a5a"
        page_bg_dark = _extract_hex(base_shell_index_css, "--color-background-dark")
        ratio = contrast_ratio(old_shared_literal, page_bg_dark)
        assert ratio < WCAG_AA_NORMAL_TEXT, (
            "expected the pre-fix scenario to reproduce as a fail; if this "
            "now passes, --color-background-dark itself changed and this "
            "historical record should be updated, not deleted"
        )


# ---------------------------------------------------------------------------
# Bug 2 — --ap-btn-primary-bg (dark mode: was 4.35:1 via shared
# --color-primary-dark, now theme-scoped)
# ---------------------------------------------------------------------------


class TestPrimaryButtonLabelContrast:
    """Given the app in {dark,light} mode, When a user reads a primary
    button's label (.btn.primary / .btn-primary / .sidebar-action.primary /
    .sidebar-action.active / .help-btn:hover — all white-on-primary fills),
    Then the white label text meets >= 4.5:1 against the button's fill."""

    WHITE = "#ffffff"

    def test_dark_mode_button_label_contrast(self, applicant_theme_css):
        # First declaration in the file is the :root (dark-default) literal;
        # the second is the .light-mode re-declaration (a var() reference,
        # not a literal — see test_light_mode_button_label_contrast instead).
        button_bg_dark = _extract_hex(applicant_theme_css, "--ap-btn-primary-bg", occurrence=0)
        ratio = contrast_ratio(self.WHITE, button_bg_dark)
        assert ratio >= WCAG_AA_NORMAL_TEXT, (
            f"dark-mode primary button: white text vs --ap-btn-primary-bg ({button_bg_dark}) "
            f"= {ratio:.2f}:1, below WCAG AA {WCAG_AA_NORMAL_TEXT}:1"
        )

    def test_light_mode_button_label_contrast(self, applicant_theme_css, base_shell_index_css):
        # Light mode's --ap-btn-primary-bg resolves to var(--ap-color-primary)
        # (declared inside .light-mode itself — see the comment on that
        # declaration in applicant-theme.css for why that resolution is safe,
        # i.e. not the same leak trap this whole fix is guarding against),
        # which chains to --color-primary -> --color-primary-light. Assert
        # against that resolved literal directly.
        effective_light_bg = _extract_hex(base_shell_index_css, "--color-primary-light")
        ratio = contrast_ratio(self.WHITE, effective_light_bg)
        assert ratio >= WCAG_AA_NORMAL_TEXT, (
            f"light-mode primary button: white text vs --color-primary-light ({effective_light_bg}) "
            f"= {ratio:.2f}:1, below WCAG AA {WCAG_AA_NORMAL_TEXT}:1"
        )

    def test_historical_bug_reproduction_dark_primary_button_borderline_fail(self, base_shell_index_css):
        """Documents the pre-fix measurement: white text directly on the
        shared --color-primary-dark (#737a81, used unscoped by the button
        before this fix) was 4.35:1 — under the 4.5:1 AA threshold."""
        color_primary_dark = _extract_hex(base_shell_index_css, "--color-primary-dark")
        ratio = contrast_ratio(self.WHITE, color_primary_dark)
        assert ratio < WCAG_AA_NORMAL_TEXT, (
            "expected the pre-fix scenario (button styled directly off the "
            "shared --color-primary-dark) to reproduce as a borderline fail; "
            "if this now passes, --color-primary-dark itself changed and "
            "this historical record should be updated, not deleted"
        )


# ---------------------------------------------------------------------------
# Bug 3 — --color-input-bg / --ap-color-text on .card/.item/.surface + inputs
# (dark mode: was a real white-on-white leak, not a false alarm — see the
# agent's report for the help.html / <input> evidence)
# ---------------------------------------------------------------------------


class TestCardAndInputSurfaceContrast:
    """Given the app in {dark,light} mode, When a user reads text inside a
    .card/.item/.surface panel or a form input that doesn't set its own
    color/background (relying on --ap-color-text on --color-input-bg),
    Then the contrast is >= 4.5:1 — not 1:1 (invisible)."""

    def test_dark_mode_card_text_vs_card_background(self, applicant_theme_css, base_shell_index_css):
        # --ap-color-text in dark mode resolves to --color-text-dark.
        text_dark = _extract_hex(base_shell_index_css, "--color-text-dark")
        card_bg_dark = _extract_hex(applicant_theme_css, "--color-input-bg-dark")
        ratio = contrast_ratio(text_dark, card_bg_dark)
        assert ratio >= WCAG_AA_NORMAL_TEXT, (
            f"dark-mode card/input text ({text_dark}) vs --color-input-bg-dark ({card_bg_dark}) "
            f"= {ratio:.2f}:1, below WCAG AA {WCAG_AA_NORMAL_TEXT}:1"
        )

    def test_light_mode_card_text_vs_card_background(self, applicant_theme_css, base_shell_index_css):
        text_light = _extract_hex(base_shell_index_css, "--color-text-light")
        card_bg_light = _extract_hex(applicant_theme_css, "--color-input-bg-light")
        ratio = contrast_ratio(text_light, card_bg_light)
        assert ratio >= WCAG_AA_NORMAL_TEXT, (
            f"light-mode card/input text ({text_light}) vs --color-input-bg-light ({card_bg_light}) "
            f"= {ratio:.2f}:1, below WCAG AA {WCAG_AA_NORMAL_TEXT}:1"
        )

    def test_historical_bug_reproduction_dark_mode_white_on_white_leak(self, base_shell_index_css):
        """Documents the pre-fix leak: with --color-input-bg a single
        #ffffff literal (no .light-mode counterpart) and --ap-color-text
        resolving to white in dark mode, any .card/.item/.surface or input
        that didn't locally override the background rendered white text on a
        white background — 1:1 contrast, i.e. fully invisible. Confirmed as
        a real (not just theoretical) leak: every bare <input>/<textarea>/
        <select> in the app styles directly off --color-input-bg + either
        --ap-color-text or --color-text, and a0-applicant/webui/help.html's
        `.surface` wrapper has no local background override at all."""
        old_shared_literal = "#ffffff"
        text_dark = _extract_hex(base_shell_index_css, "--color-text-dark")
        ratio = contrast_ratio(text_dark, old_shared_literal)
        assert ratio == pytest.approx(1.0, abs=0.01), (
            "expected the pre-fix scenario (white text on the old shared "
            "white --color-input-bg literal) to reproduce as ~1:1 "
            "(indistinguishable); if this changed, --color-text-dark itself "
            "changed and this historical record should be updated, not "
            "deleted"
        )
