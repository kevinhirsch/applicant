"""Regression coverage for the §G Content-routes design-audit fix batch,
calendar.js slice (items 126-130 and the calendar half of #136), confined to
``static/js/calendar.js`` (+ the CSS facts it depends on in
``static/style.css``).

Follows the convention of ``tests/bdd/steps/test_enh_uia11y_steps.py`` /
``workspace/tests/test_applicant_round1_chatmind.py``: every fact is read
from the actual static file content via ``pathlib`` + regex — no browser, no
DOM, no real socket.

Each assertion here was verified, by hand, to actually go red when the
underlying fix is reverted (revert source -> rerun -> see the assertion
fail -> restore via ``git checkout``) per the batch's test-coverage DoD.
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
JS_DIR = REPO_ROOT / "workspace" / "static" / "js"
STYLE_CSS = REPO_ROOT / "workspace" / "static" / "style.css"
CALENDAR_JS = JS_DIR / "calendar.js"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# ── #126: event-tag label is monochrome, hue lives only on the dot ────────

def test_agenda_event_tag_hue_lives_only_on_the_dot():
    """The agenda's per-event `#type` tag used to color its whole label with
    the event-type hue. Now the `.cal-event-tag` span carries no inline
    color and only the small leading `.cal-event-tag-dot` gets the
    per-type background color."""
    src = _read(CALENDAR_JS)
    m = re.search(
        r"const _typeTag = ev\.event_type\s*\n?\s*\?\s*`([^`]*)`",
        src,
    )
    assert m, "expected to find the agenda _typeTag template"
    tag_markup = m.group(1)
    # The dot carries the per-type color inline.
    dot = re.search(
        r'<span class="cal-event-tag-dot" style="background:\$\{[^}]*\}"></span>',
        tag_markup,
    )
    assert dot, "expected the type-color to live on .cal-event-tag-dot"
    # The outer .cal-event-tag span itself must not carry an inline color/
    # background style keyed off the event type — only the CSS class.
    outer_open = tag_markup.split(dot.group(0))[0]
    assert re.fullmatch(r'<span class="cal-event-tag">', outer_open), (
        f".cal-event-tag opening tag must carry no inline style, got: {outer_open!r}"
    )

    css = _read(STYLE_CSS)
    tag_block = re.search(r"\.cal-event-tag\s*\{([^}]*)\}", css)
    assert tag_block, "expected a .cal-event-tag rule in style.css"
    # Monochrome ink: derived from --fg, not from any per-type palette var.
    assert re.search(r"color:\s*color-mix\(in srgb,\s*var\(--fg\)", tag_block.group(1)), (
        ".cal-event-tag text color must be a neutral fg-derived tone"
    )


# ── #127: legible row text + real min-height ───────────────────────────────

def test_cal_event_row_text_and_height_are_legible():
    """`.cal-event-row-name`/`-time` were 9px (sub-legible); `.cal-event-row`
    had no real minimum height. Both are now raised: >=11px text and a
    28px row minimum height."""
    css = _read(STYLE_CSS)
    row = re.search(r"\.cal-event-row\s*\{([^}]*)\}", css)
    assert row, "expected a .cal-event-row rule"
    mh = re.search(r"min-height:\s*(\d+)px", row.group(1))
    assert mh and int(mh.group(1)) >= 28, ".cal-event-row must have min-height >= 28px"

    name = re.search(r"\.cal-event-row-name\s*\{([^}]*)\}", css)
    assert name, "expected a .cal-event-row-name rule"
    name_fs = re.search(r"font-size:\s*(\d+)px", name.group(1))
    assert name_fs and int(name_fs.group(1)) >= 11, ".cal-event-row-name must be >=11px"

    time_ = re.search(r"\.cal-event-row-time\s*\{([^}]*)\}", css)
    assert time_, "expected a .cal-event-row-time rule"
    time_fs = re.search(r"font-size:\s*(\d+)px", time_.group(1))
    assert time_fs and int(time_fs.group(1)) >= 11, ".cal-event-row-time must be >=11px"


def test_cal_multiday_bar_text_and_height_are_legible():
    """`.cal-multiday` bars were 8px text / 11px tall — raised to 11px text /
    16px tall, and the mobile override must not shrink the font back down
    (it only tightens padding)."""
    css = _read(STYLE_CSS)
    md = re.search(r"\.cal-multiday\s*\{([^}]*)\}", css)
    assert md, "expected a .cal-multiday rule"
    fs = re.search(r"font-size:\s*(\d+)px", md.group(1))
    assert fs and int(fs.group(1)) >= 11, ".cal-multiday font-size must be >=11px"
    ht = re.search(r"height:\s*(\d+)px", md.group(1))
    assert ht and int(ht.group(1)) >= 16, ".cal-multiday height must be >=16px"

    # Mobile override lives in the calendar's own max-width:600px block
    # (identified by containing .cal-modal-container, since the stylesheet
    # has several unrelated max-width:600px blocks for other features).
    cal_mobile_start = css.index("@media (max-width: 600px)", css.index(".cal-modal-container") - 200)
    mobile_slice = css[cal_mobile_start:cal_mobile_start + 4000]
    mobile_md = re.search(r"\.cal-multiday\s*\{([^}]*)\}", mobile_slice)
    assert mobile_md, "expected a mobile .cal-multiday override in the calendar's own media block"
    assert "font-size" not in mobile_md.group(1), (
        "mobile .cal-multiday override must not shrink font-size back down"
    )


# ── #128: shared _calBarStyle() helper, low-alpha tint + solid edge ───────

def test_cal_bar_style_helper_used_by_multiday_and_week_allday():
    """`_calBarStyle()` replaces raw saturated background bars with a
    low-alpha tint + solid colored left edge + neutral ink, and is used by
    both the month-view multiday bar and the week-view all-day bar."""
    src = _read(CALENDAR_JS)
    fn = re.search(r"function _calBarStyle\(ev\) \{(.*?)\n\}\n", src, re.S)
    assert fn, "expected a _calBarStyle(ev) function"
    body = fn.group(1)
    assert re.search(r"color-mix\(in srgb,\s*\$\{c\}\s*24%,\s*var\(--bg\)\)", body), (
        "_calBarStyle must produce a low-alpha tinted background"
    )
    assert re.search(r"border-left:\s*3px solid \$\{c\}", body), (
        "_calBarStyle must produce a solid colored left edge"
    )
    assert re.search(r"color:\s*var\(--fg\)", body), (
        "_calBarStyle must keep the ink neutral"
    )
    # Used at both call sites.
    assert "cal-multiday" in src and "_calBarStyle(md)" in src, (
        "expected the month multiday bar to call _calBarStyle(md)"
    )
    assert re.search(r'cal-wk-allday-event"[^>]*style="\$\{_calBarStyle\(ev\)\}"', src), (
        "expected the week all-day bar to call _calBarStyle(ev) inline"
    )


# ── #129: toolbar overflow menu + guarded outside-click listener ──────────

def test_toolbar_overflow_menu_collapses_settings_refresh_filters():
    """Settings / Refresh / Filters must be collapsed into `.cal-more-wrap`
    so the toolbar reads as nav | view-segment | +New, not 5+ loose
    controls."""
    src = _read(CALENDAR_JS)
    header = re.search(r"function _headerHTML\(\)\s*\{(.*?)\n\}\n", src, re.S)
    assert header, "expected to find _headerHTML()"
    html = header.group(1)

    nav_idx = html.index("cal-toolbar-nav")
    view_idx = html.index("cal-view-toggle")
    more_wrap_idx = html.index('class="cal-more-wrap"')
    settings_idx = html.index('id="cal-settings"')
    sync_idx = html.index('id="cal-sync"')
    add_idx = html.index("cal-add-btn")

    # Group order: nav, then view-segment, then the overflow wrap, then +New.
    assert nav_idx < view_idx < more_wrap_idx < add_idx, (
        "toolbar groups must read nav | view-segment | more-wrap | +New"
    )
    # Settings + Refresh (Sync) buttons must live inside the overflow wrap,
    # not as loose top-level toolbar controls.
    menu_idx = html.index('id="cal-more-menu"')
    assert more_wrap_idx < menu_idx < settings_idx < add_idx, (
        "Settings must be nested inside the overflow menu, ahead of +New"
    )
    assert more_wrap_idx < sync_idx < add_idx, (
        "Refresh/Sync must be nested inside the overflow menu, ahead of +New"
    )
    assert "_filtersToggleHTML()" in html, (
        "Filters toggle must be rendered inside the overflow menu markup"
    )


def test_more_menu_outside_click_listener_is_guarded_against_duplicates():
    """The outside-click-close listener for the overflow menu must be wired
    once per #cal-body (guarded by `body._calMoreWired`), not stacked on
    every re-render (which would leak duplicate document listeners)."""
    src = _read(CALENDAR_JS)
    m = re.search(
        r"if \(!body\._calMoreWired\)\s*\{\s*body\._calMoreWired = true;\s*"
        r"document\.addEventListener\('click',",
        src,
    )
    assert m, (
        "expected a body._calMoreWired guard around the outside-click "
        "document listener for the overflow menu"
    )


# ── #130: keyboard-focusable event rows ────────────────────────────────────

def test_cal_event_row_is_keyboard_operable():
    """Month-cell `.cal-event-row`s must be tabindex="0" with a focus-visible
    ring, and an Enter/Space keydown handler must trigger the row's click
    (so keyboard users can open an event without a mouse)."""
    src = _read(CALENDAR_JS)
    assert re.search(r'class="cal-event-row" tabindex="0"', src), (
        "expected .cal-event-row markup to carry tabindex=\"0\""
    )
    handler = re.search(
        r"body\.querySelectorAll\('\.cal-event-row\[tabindex\]'\)\.forEach\(el => \{\s*"
        r"el\.addEventListener\('keydown', \(e\) => \{\s*"
        r"if \(e\.key === 'Enter' \|\| e\.key === ' '\) \{ e\.preventDefault\(\); el\.click\(\); \}",
        src,
    )
    assert handler, "expected an Enter/Space keydown handler calling el.click()"

    css = _read(STYLE_CSS)
    row = re.search(r"\.cal-event-row:focus-visible\s*\{([^}]*)\}", css)
    assert row, "expected a .cal-event-row:focus-visible rule"
    assert "outline" in row.group(1) and "none" not in row.group(1)


# ── #136 (calendar half): agenda "Create event" CTA is a real button ──────

def test_agenda_empty_state_create_event_is_a_real_primary_button():
    """The agenda empty state's "Create event" CTA used to be underlined
    accent-red link text pretending to be a button. It must now be a real
    `.cal-btn.cal-btn-primary` button; the secondary "Settings ›
    Integrations" link stays a link, recolored to --sys-blue."""
    src = _read(CALENDAR_JS)
    start = src.index("if (!dates.length) {")
    end = src.index("} else {", start)
    block = src[start:end]
    assert re.search(
        r'<button type="button" class="cal-btn cal-btn-primary" data-cal-create-event="1">Create event</button>',
        block,
    ), "expected a real primary button for Create event"
    link = re.search(r'<a href="#" data-cal-open-settings="integrations"[^>]*>', block)
    assert link, "expected the Settings › Integrations link"
    assert "color:var(--sys-blue)" in link.group(0), (
        "the secondary Settings link must be recolored to --sys-blue"
    )
    # No more accent-red underlined link masquerading as the primary CTA.
    assert "var(--red)" not in block and "var(--accent" not in block
