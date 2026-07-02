"""Regression coverage for the §G Content-routes design-audit fix batch,
Memory/Tasks/Library slice (items 122, 123, 124, 125, 131, 132, 133, 134,
135, 143, 146), confined to ``static/js/memory.js``, ``static/js/tasks.js``,
``static/js/documentLibrary.js`` (+ the CSS facts they depend on in
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
MEMORY_JS = JS_DIR / "memory.js"
TASKS_JS = JS_DIR / "tasks.js"
DOCLIB_JS = JS_DIR / "documentLibrary.js"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _strip_css_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _strip_js_line_comments(src: str) -> str:
    return re.sub(r"//[^\n]*", "", src)


# ── #143: the shared .ow-list-row primitive itself ─────────────────────────

def test_ow_list_row_primitive_has_expected_base_properties():
    """`.ow-list-row` is the single flat-row treatment adopted across Memory/
    Tasks/Library/Email: a hairline bottom separator, a hover-only fill, a
    >=44px minimum height, and a system-blue focus-visible ring."""
    css = _read(STYLE_CSS)
    base = re.search(r"(?<!\.)\.ow-list-row\s*\{([^}]*)\}", css)
    assert base, "expected a base .ow-list-row rule"
    block = base.group(1)
    mh = re.search(r"min-height:\s*(\d+)px", block)
    assert mh and int(mh.group(1)) >= 44, ".ow-list-row must have min-height >= 44px"
    assert re.search(r"border-bottom:\s*1px solid var\(--border\)", block), (
        ".ow-list-row must supply a hairline bottom separator"
    )
    assert re.search(r"background:\s*transparent", block), (
        ".ow-list-row must default to a transparent (non-tile) background"
    )
    hover = re.search(r"\.ow-list-row:hover\s*\{([^}]*)\}", css)
    assert hover and "background" in hover.group(1), (
        ".ow-list-row:hover must supply a hover-only fill"
    )
    focus = re.search(r"\.ow-list-row:focus-visible\s*\{([^}]*)\}", css)
    assert focus and "var(--sys-blue)" in focus.group(1), (
        ".ow-list-row:focus-visible must ring in --sys-blue"
    )


# ── #122: memory.js adopts ow-list-row at both render call sites ──────────

def test_memory_rows_adopt_ow_list_row_at_both_call_sites():
    """Memory's normal render path and its inline-edit render path must both
    stamp the flat-row primitive class onto `.memory-item` rows."""
    src = _read(MEMORY_JS)
    assert re.search(r"item\.className = 'memory-item ow-list-row'", src), (
        "expected the normal memory-item render to add ow-list-row"
    )
    assert re.search(r"item\.className = 'memory-item ow-list-row memory-item-editing'", src), (
        "expected the inline-edit memory-item render to add ow-list-row"
    )


def test_memory_item_ow_list_row_compound_override_flattens_the_tile():
    """`.memory-item.ow-list-row` must win on specificity over the base
    (deliberately untouched) `.memory-item` tile rule and drop the top/
    left/right borders + radius + tinted background, keeping only the
    hairline bottom separator supplied by `.ow-list-row`."""
    css = _read(STYLE_CSS)
    # The base rule is untouched: still a full bordered/tinted tile.
    base = re.search(r"\.memory-item\s*\{([^}]*)\}", css)
    assert base, "expected the base .memory-item rule to still exist"
    assert re.search(r"border:\s*1px solid var\(--border\)", base.group(1)), (
        "the base .memory-item rule must remain untouched (still a full tile border)"
    )
    # The compound override flattens it.
    compound = re.search(r"\.memory-item\.ow-list-row\s*\{([^}]*)\}", css)
    assert compound, "expected a .memory-item.ow-list-row compound override"
    block = compound.group(1)
    assert re.search(r"border-top:\s*none", block)
    assert re.search(r"border-left:\s*none", block)
    assert re.search(r"border-right:\s*none", block)
    assert re.search(r"border-radius:\s*0", block)
    assert re.search(r"background:\s*transparent", block)
    # border-bottom must NOT be touched here (left to .ow-list-row's hairline).
    # (Strip the explanatory comment first — it mentions "border-bottom" in
    # prose, which isn't a declaration.)
    block_no_comments = _strip_css_comments(block)
    assert "border-bottom" not in block_no_comments


# ── #123: synapse-sweep ::after + @keyframes + @property fully removed ────

def test_synapse_sweep_pseudo_element_and_keyframes_are_fully_removed():
    """The per-row infinite light-sweep animation (`::after` pseudo-element,
    its `@keyframes`, and `@property --sweep`) must be gone entirely — not
    merely gated behind prefers-reduced-motion."""
    css = _strip_css_comments(_read(STYLE_CSS))
    assert "synapse-sweep" not in css, (
        "the synapse-sweep animation/pseudo-element must be fully removed, "
        "not just reduced-motion-gated"
    )
    assert "@property --sweep" not in css, (
        "the --sweep custom property must be fully removed"
    )


# ── #124: dead memory-synapse-pulse keyframes + neutralized rule removed ──

def test_memory_synapse_pulse_keyframes_are_removed():
    """The dead `@keyframes memory-synapse-pulse` and its neutralized
    `.memory-modal-content` ::before / reduced-motion rule must be gone."""
    css = _read(STYLE_CSS)
    assert "memory-synapse-pulse" not in css, (
        "the dead memory-synapse-pulse keyframes must be fully removed"
    )
    modal_content = re.search(r"\.memory-modal-content\s*\{([^}]*)\}", css)
    assert modal_content, "expected the .memory-modal-content rule to still exist"
    # No lingering ::before selector scoped to memory-modal-content either.
    assert not re.search(r"\.memory-modal-content(?:\s*::before|\s*\.\w+::before)", css), (
        "expected no leftover .memory-modal-content ::before rule"
    )


# ── #125: pinned rows conveyed by the neutral pin-dot glyph, not red tint ─

def test_memory_pinned_row_no_longer_tints_red():
    """`.memory-pinned` / `:hover` must not set a red border-left or red
    background — pinned state is conveyed only by the `.memory-pin-dot`
    glyph filling in."""
    css = _read(STYLE_CSS)
    pinned = re.search(r"(?<!:hover)\n\.memory-pinned\s*\{([^}]*)\}", css)
    assert pinned, "expected a .memory-pinned rule"
    block = pinned.group(1)
    assert "var(--red)" not in block, ".memory-pinned must not tint red"
    assert "border-left" not in block, ".memory-pinned must not set a red border-left"

    hover = re.search(r"\.memory-pinned:hover\s*\{([^}]*)\}", css)
    assert hover, "expected a .memory-pinned:hover rule"
    assert "var(--red)" not in hover.group(1), ".memory-pinned:hover must not tint red"

    # The neutral pin-dot glyph exists and is the carrier of pinned state.
    src = _read(MEMORY_JS)
    assert "memory-pinned" in src, "expected memory.js to still apply memory-pinned"
    dot = re.search(r"\.memory-pin-dot\s*\{([^}]*)\}", css)
    assert dot, "expected a .memory-pin-dot rule to exist as the pinned-state glyph"


# ── #131: tasks.js adopts ow-list-row at both render call sites ───────────

def test_task_cards_adopt_ow_list_row_at_both_call_sites():
    """The task-list render and the Add-Task preset picker must both stamp
    the flat-row primitive onto their `.memory-item task-card` rows."""
    src = _read(TASKS_JS)
    assert re.search(
        r"card\.className = 'memory-item ow-list-row task-card'",
        src,
    ), "expected the task list render to add ow-list-row"
    assert re.search(
        r'class="memory-item ow-list-row task-card"',
        src,
    ), "expected the preset-picker buttons to carry ow-list-row"


# ── #132: _statusDot() glow removed; .task-status-badge is a flat pill ────

def test_status_dot_has_no_glow_and_badge_is_flat_chrome():
    """`_statusDot()` must render a plain dot (no box-shadow halo), and
    `.task-status-badge` must be a neutral flat chrome pill — hue kept only
    on the paused/run-now glyph or the active badge's small dot."""
    src = _read(TASKS_JS)
    fn = re.search(r"function _statusDot\(status\) \{(.*?)\n\}\n", src, re.S)
    assert fn, "expected a _statusDot(status) function"
    assert "box-shadow" not in _strip_js_line_comments(fn.group(1)), (
        "_statusDot must not render a glow (box-shadow)"
    )

    css = _read(STYLE_CSS)
    badge = re.search(r"\.task-status-badge\s*\{([^}]*)\}", css)
    assert badge, "expected a .task-status-badge rule"
    block = badge.group(1)
    assert "box-shadow" not in block, ".task-status-badge must be a flat pill (no glow)"
    assert re.search(r"background:\s*color-mix\(in srgb,\s*var\(--fg\)", block), (
        ".task-status-badge background must be neutral (fg-derived), not hued"
    )
    assert re.search(r"color:\s*color-mix\(in srgb,\s*var\(--fg\)", block), (
        ".task-status-badge text color must be neutral (fg-derived), not hued"
    )
    # Hue survives only on the glyph / small dot carriers.
    assert re.search(r"\.task-active-badge::before\s*\{[^}]*background:\s*var\(--green", css), (
        "expected the active badge's small dot to still carry its color"
    )


# ── #133: task log-preview row is neutral, color only on the glyph ────────

def test_task_log_preview_row_is_neutral_except_the_glyph():
    """The last-run log-preview row's border/background must be neutral;
    color is kept only on the tiny ✗/✓ glyph span."""
    src = _read(TASKS_JS)
    m = re.search(
        r"const lr = document\.createElement\('div'\);\s*\n\s*"
        r"lr\.style\.cssText = `([^`]*)`;",
        src,
    )
    assert m, "expected to find the log-preview row's style assembly"
    row_style = m.group(1)
    assert "border-left:2px solid var(--border)" in row_style, (
        "the log-preview row border must be neutral (var(--border)), not hued"
    )
    assert re.search(r"background:color-mix\(in srgb, var\(--fg\)", row_style), (
        "the log-preview row background must be neutral (fg-derived), not hued"
    )
    assert not re.search(r"(?<![\w-])color:", row_style), (
        "the row's own style must carry no standalone color: declaration "
        "(color-mix() calls for background/border are fine) — only the "
        "glyph span should set text color"
    )
    inner = re.search(r"lr\.innerHTML = `([^`]*)`;", src)
    assert inner, "expected the log-preview row's inner glyph+text markup"
    assert re.search(r"<span style=\"font-weight:600;color:\$\{color\};\">", inner.group(1)), (
        "color must be scoped to the tiny glyph span only"
    )


# ── #134: doclib-card.ow-list-row compound override; applicant card exempt ─

def test_doclib_card_ow_list_row_compound_keeps_border_bottom_only():
    """`.doclib-card.ow-list-row` must keep the bottom border (Library's
    flat-row treatment) but drop the other three sides + radius, mirroring
    the Memory compound override."""
    css = _read(STYLE_CSS)
    compound = re.search(r"\.doclib-card\.ow-list-row\s*\{([^}]*)\}", css)
    assert compound, "expected a .doclib-card.ow-list-row compound override"
    block = compound.group(1)
    assert re.search(r"border-top:\s*none", block)
    assert re.search(r"border-left:\s*none", block)
    assert re.search(r"border-right:\s*none", block)
    assert re.search(r"border-radius:\s*0", block)
    assert "border-bottom" not in _strip_css_comments(block), (
        "border-bottom must be left alone (supplied by .ow-list-row's hairline)"
    )


def test_applicant_materials_card_never_gets_ow_list_row():
    """The applicant materials card (`_applicantCard`) must keep its full
    tile chrome and never be flattened by `ow-list-row`."""
    src = _read(DOCLIB_JS)
    fn = re.search(r"function _applicantCard\(item, appId, results\) \{(.*?)\n    \}\n", src, re.S)
    assert fn, "expected to find _applicantCard()"
    assert "ow-list-row" not in fn.group(1), (
        "_applicantCard must never carry the ow-list-row class"
    )
    assert "card.className = 'doclib-card memory-item';" in fn.group(1), (
        "_applicantCard must keep its plain tile class list"
    )


def test_expanded_doclib_card_reasserts_full_tile_chrome_by_source_order():
    """`.doclib-card.doclib-card-expanded` re-asserts full card framing
    (border/background/radius) at the same class-count specificity as
    `.doclib-card.ow-list-row`; it must win the tie by coming later in the
    stylesheet's source order."""
    css = _read(STYLE_CSS)
    flat_idx = css.index(".doclib-card.ow-list-row {")
    # Anchor to a standalone rule (start of line) so we don't match a scoped
    # compound selector list like "#memory-modal .doclib-card.doclib-card-
    # expanded {" elsewhere in the file.
    expanded = re.search(
        r"^\.doclib-card\.doclib-card-expanded\s*\{([^}]*)\}", css, re.M
    )
    assert expanded, "expected a standalone .doclib-card.doclib-card-expanded rule"
    expanded_idx = expanded.start()
    assert expanded_idx > flat_idx, (
        ".doclib-card.doclib-card-expanded must come after .doclib-card.ow-list-row "
        "in source order so it wins the specificity tie"
    )
    block = expanded.group(1)
    assert re.search(r"border:\s*1px solid var\(--border\)", block), (
        "the expanded card must re-assert a full tile border"
    )
    assert re.search(r"border-radius:\s*8px", block), (
        "the expanded card must re-assert the tile radius"
    )


# ── #135: selection highlight uses --sys-blue, not --red ──────────────────

def test_selection_highlight_uses_sys_blue_not_red():
    """The shared `:has(.memory-select-cb:checked)` selection-highlight rule
    (Memory/Library/chat rows) must use the system-blue accent, not the
    theme's red accent — selection is a system state, not a brand color."""
    css = _read(STYLE_CSS)
    m = re.search(
        r"\.memory-item:has\(\.memory-select-cb:checked\),\s*\n"
        r"\.doclib-card:has\(\.memory-select-cb:checked\),\s*\n"
        r"\.doclib-chat-row:has\(\.memory-select-cb:checked\)\s*\{([^}]*)\}",
        css,
    )
    assert m, "expected the shared selection-highlight :has() rule"
    block = m.group(1)
    assert "var(--sys-blue)" in block, "selection highlight must use --sys-blue"
    assert "var(--red)" not in block, "selection highlight must not use --red"


# ── #146: transitions scoped to specific properties, not `all` ────────────

def test_doclib_card_base_transition_is_scoped_not_all():
    """`.doclib-card`'s base rule must scope its `transition` to specific
    properties rather than the unbounded `transition: all`."""
    css = _read(STYLE_CSS)
    # Anchor to the standalone base rule (start of line) — a couple of other
    # `.doclib-card { ... }` occurrences exist nested inside unrelated
    # reduced-motion/animation media blocks earlier in the file.
    base = re.search(r"^\.doclib-card\s*\{([^}]*)\}", css, re.M)
    assert base, "expected the base .doclib-card rule"
    transition = re.search(r"transition:\s*([^;]+);", base.group(1))
    assert transition, ".doclib-card must declare a transition"
    assert "all" not in transition.group(1), (
        f".doclib-card transition must be scoped, not 'all', got: {transition.group(1)!r}"
    )


def test_memory_item_ow_list_row_carries_its_own_scoped_transition():
    """`.memory-item.ow-list-row` must carry its own scoped transition
    (background-color, border-color) — distinct from (and overriding) the
    base `.memory-item` rule's `transition: all`, which is deliberately
    left untouched."""
    css = _read(STYLE_CSS)
    base = re.search(r"\.memory-item\s*\{([^}]*)\}", css)
    assert base, "expected the base .memory-item rule"
    assert re.search(r"transition:\s*all\b", base.group(1)), (
        "the base .memory-item rule is intentionally left with transition: all"
    )
    compound = re.search(r"\.memory-item\.ow-list-row\s*\{([^}]*)\}", css)
    assert compound, "expected the .memory-item.ow-list-row compound override"
    transition = re.search(r"transition:\s*([^;]+);", compound.group(1))
    assert transition, ".memory-item.ow-list-row must declare its own transition"
    assert "all" not in transition.group(1), (
        ".memory-item.ow-list-row's own transition must be scoped, not 'all'"
    )
    assert "background-color" in transition.group(1) and "border-color" in transition.group(1)


# ── #136 (Library half): Import CTA is a real primary button ──────────────

def test_library_empty_state_import_cta_is_a_real_primary_button():
    """The Library empty state's "Import" CTA used to be underlined
    accent-red link text; it must now be a real `.cal-btn.cal-btn-primary`
    button wired to the existing import-file control."""
    src = _read(DOCLIB_JS)
    assert re.search(
        r'<button type="button" class="cal-btn cal-btn-primary" id="doclib-empty-import">Import',
        src,
    ), "expected a real primary button for the Library empty-state Import CTA"
    assert "doclib-import-file-btn')?.click()" in src, (
        "the Import CTA must be wired to the existing import-file control, "
        "not dead/duplicate logic"
    )
