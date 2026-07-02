"""Regression coverage for round 2 / wave 1, PRODUCT_EXHAUSTIVE_AUDIT.md Top-25
item #20 (icon-rail half): "aria-labels on icon-only rail + close buttons".

Confined to ``workspace/static/index.html`` — the main app-shell static markup.
The icon-only sidebar/rail buttons (``.icon-rail-btn``, the hamburger toggles)
and the icon-only ``.close-btn`` modal-close buttons rendered directly as
static markup in this file had no ``aria-label``, so a screen-reader user had
no accessible name for them (just a bare glyph/SVG). Fixed by adding an
``aria-label`` to each, matching the established phrasing convention already
used elsewhere in this file (copy the existing ``title`` text verbatim for
rail buttons — see e.g. ``#rail-activity``/``#rail-assistant``; "Close <thing>
modal" for close buttons — see e.g. ``#close-memory-modal``).

Out of scope (per the batch brief — not present as static markup in this
file, or owned by a different concurrent agent this round):
  - The Activity status-strip live region (owned by a different agent working
    in ``applicantActivity.js``).
  - Any icon-only button built dynamically via JS template literals (e.g.
    per-message action buttons, dynamically-rendered modal chrome) — those
    live in other files and are other batches' responsibility.
  - The ``tool-*-btn`` sidebar list items (``#tool-memory-btn`` etc.) are NOT
    icon-only — each already carries a visible ``<span class="grow">Label</span>``
    text node, so they already have an accessible name and needed no change.

Follows the convention of ``test_applicant_round1_remainder_shell.py`` /
``test_applicant_round1_onboarding.py``: every fact is read from the actual
static file content via ``pathlib`` + regex — no browser, no DOM, no real
socket.

Each assertion here was verified, by hand, to go red when the corresponding
aria-label attribute is reverted (temporarily removed) and green again once
restored, per the batch's test-coverage DoD.
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
INDEX_HTML = REPO_ROOT / "workspace" / "static" / "index.html"


def _read() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


def _button_tag(html: str, element_id: str) -> str:
    """Return the full opening `<button ...>` tag for a given `id="..."`,
    tolerant of attribute order. Fails loudly if the id isn't found or isn't
    on a <button> element."""
    m = re.search(rf'<button\b[^>]*\bid="{re.escape(element_id)}"[^>]*>', html)
    assert m, f'expected a <button id="{element_id}"> tag in index.html'
    return m.group(0)


def _attr(tag: str, name: str) -> str | None:
    m = re.search(rf'{name}="([^"]*)"', tag)
    return m.group(1) if m else None


# ── Icon-only rail buttons: aria-label matches the existing title verbatim ──

RAIL_BUTTONS_MATCH_TITLE = [
    "rail-search-btn",
    "rail-new-session",
    "rail-delete-session",
    "rail-chats",
    "rail-documents",
    "rail-portal",
    "rail-research",
    "rail-calendar",
    "rail-theme",
    "rail-compare",
    "rail-cookbook",
    "rail-gallery",
    "rail-notes",
    "rail-tasks",
    "rail-update",
    "rail-settings",
]


def test_icon_rail_buttons_have_aria_label_matching_title():
    html = _read()
    for element_id in RAIL_BUTTONS_MATCH_TITLE:
        tag = _button_tag(html, element_id)
        title = _attr(tag, "title")
        label = _attr(tag, "aria-label")
        assert title, f"expected #{element_id} to carry a title attribute (test setup sanity)"
        assert label, f"expected #{element_id} to have an aria-label (icon-only rail button)"
        assert label == title, (
            f"#{element_id}: aria-label {label!r} should match the existing "
            f"title {title!r} per the established phrasing convention"
        )


def test_icon_rail_buttons_all_carry_the_icon_rail_btn_class():
    """Sanity check that the ids above are actually the icon-only rail
    buttons this item targets (not some unrelated element that happens to
    share an id substring)."""
    html = _read()
    for element_id in RAIL_BUTTONS_MATCH_TITLE:
        tag = _button_tag(html, element_id)
        assert "icon-rail-btn" in tag, f"expected #{element_id} to carry class icon-rail-btn"


# ── Sidebar/rail toggle buttons ─────────────────────────────────────────────

def test_hamburger_btn_has_aria_label():
    html = _read()
    tag = _button_tag(html, "hamburger-btn")
    assert _attr(tag, "aria-label") == "Show sidebar", (
        "expected #hamburger-btn aria-label to match its title 'Show sidebar'"
    )


def test_sidebar_toggle_btn_has_aria_label():
    html = _read()
    tag = _button_tag(html, "sidebar-toggle-btn")
    assert _attr(tag, "aria-label") == "Toggle sidebar", (
        "expected #sidebar-toggle-btn aria-label to match its title 'Toggle sidebar', "
        "consistent with the pre-existing #mobile-menu-btn aria-label"
    )


def test_mobile_menu_btn_aria_label_unchanged():
    """#mobile-menu-btn already had an aria-label before this batch — confirm
    it is still present and untouched (not a regression target, just a
    guard against an accidental edit nearby)."""
    html = _read()
    tag = _button_tag(html, "mobile-menu-btn")
    assert _attr(tag, "aria-label") == "Toggle sidebar"


# ── Icon-only .close-btn modal-close buttons ────────────────────────────────

def test_close_theme_popup_has_aria_label():
    html = _read()
    tag = _button_tag(html, "close-theme-popup")
    assert "close-btn" in tag
    assert _attr(tag, "aria-label") == "Close theme modal"


def test_close_custom_preset_has_aria_label():
    html = _read()
    tag = _button_tag(html, "close-custom-preset")
    assert "close-btn" in tag
    assert _attr(tag, "aria-label") == "Close prompt modal"


def test_close_cookbook_modal_has_aria_label():
    html = _read()
    tag = _button_tag(html, "close-cookbook-modal")
    assert "close-btn" in tag
    assert _attr(tag, "aria-label") == "Close cookbook modal"


def test_settings_modal_close_btn_has_aria_label():
    """The Settings modal's close button (unlike the others) carries no id in
    the markup — locate it via the unique settings-opacity-wrap toggle that
    immediately precedes it in the same modal-header."""
    html = _read()
    anchor = 'id="settings-opacity-wrap"'
    assert anchor in html, "expected #settings-opacity-wrap to exist (test anchor sanity)"
    idx = html.index(anchor)
    window = html[idx : idx + 1500]
    m = re.search(r'<button type="button" class="close-btn"[^>]*>', window)
    assert m, "expected a .close-btn button shortly after #settings-opacity-wrap"
    tag = m.group(0)
    assert 'id="' not in tag, (
        "test setup sanity: the settings close-btn is expected to still have no id "
        "(if this now fails, another agent may have added one — update the anchor logic)"
    )
    assert _attr(tag, "aria-label") == "Close settings modal"


# ── Pre-existing close-btn aria-labels: confirm untouched, still present ───

def test_preexisting_close_btn_aria_labels_untouched():
    html = _read()
    tag = _button_tag(html, "close-memory-modal")
    assert _attr(tag, "aria-label") == "Close memory modal"
    tag = _button_tag(html, "close-rename-session")
    assert _attr(tag, "aria-label") == "Close rename session modal"


# ── Every static-markup .close-btn in the file now has an aria-label ───────

def test_every_close_btn_occurrence_has_an_aria_label():
    html = _read()
    for m in re.finditer(r'<button type="button" class="close-btn"[^>]*>', html):
        tag = m.group(0)
        assert "aria-label=" in tag, f"expected every .close-btn to carry an aria-label, got: {tag}"


# ── Every static icon-rail-btn in the file now has an aria-label ───────────

def test_every_icon_rail_btn_occurrence_has_an_aria_label():
    html = _read()
    count = 0
    for m in re.finditer(r'<button type="button" class="icon-rail-btn[^"]*"[^>]*>', html):
        tag = m.group(0)
        count += 1
        assert "aria-label=" in tag, f"expected every .icon-rail-btn to carry an aria-label, got: {tag}"
    assert count >= len(RAIL_BUTTONS_MATCH_TITLE), (
        "sanity: expected to find at least as many icon-rail-btn occurrences as "
        "the ids this test explicitly tracks"
    )


# ── Not-icon-only sidebar list items: unaffected, no aria-label needed ─────

def test_tool_list_items_have_visible_text_and_were_not_touched():
    """`#tool-memory-btn` etc. are `<div class="list-item">`, not buttons, and
    already carry a visible `<span class="grow">Label</span>` text node — so
    they were correctly left alone by this batch. Guard against a regression
    where someone assumes these need aria-label too and starts hand-rolling
    one that drifts from the visible text."""
    html = _read()
    m = re.search(r'<div class="list-item" id="tool-memory-btn">.*?</div>', html, re.DOTALL)
    assert m, "expected #tool-memory-btn markup"
    block = m.group(0)
    assert '<span class="grow">Brain</span>' in block
    assert "aria-label" not in block
