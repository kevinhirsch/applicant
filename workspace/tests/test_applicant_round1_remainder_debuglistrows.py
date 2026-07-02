"""Regression coverage for the §E Observability design-audit items #93/#100,
the two remainder items ``tests/test_applicant_round1_observability.py``
explicitly documented as NOT actually implemented at that batch's
test-authoring time (see that file's module docstring: item #93 "remains NOT
implemented ... Still SKIPPED", item #100 "out of scope ... folded into
#93/#94").

Confined to ``static/js/applicantDebug.js`` (+ the pre-existing
``.applicant-debug-list`` / ``.applicant-debug-list-row`` CSS pair in
``static/style.css``, read-only reference — no new CSS was needed, the fix
reuses the pair the Activity/Logs rows already use).

Item #93: the Sources and Tools Config sub-section toggle rows rendered one
bordered ``.admin-card`` per row (stacked tiles). Fixed to use the same
``.applicant-debug-list-row`` hairline-divided flat-list treatment
``_renderActivity``/``_renderLogs`` already use (see
``test_activity_rows_use_list_row_with_demoted_secondary_action`` /
``test_logs_tab_renders_structured_rows_and_download_button_not_copy`` in the
observability test file for that established precedent). The existing
``.applicant-debug-list-row`` layout (``display:flex; align-items:center;
justify-content:space-between; gap:10px``) already matches the toggle-row
markup's own pre-fix inline flex styles exactly, so no compatible variant
class was needed — confirmed below.

Item #100 (a generic "``.admin-card`` stacked = glass-on-glass" finding):
resolved for Sources/Tools by the #93 fix above. While confirming no OTHER
remaining ``.admin-card``-stacking instance was left in
``applicantDebug.js``'s rendered views, two more were found beyond the
Sources/Tools pair — real, additional instances of the identical pattern
(a `.map(...).join('')` of per-item `.admin-card` tiles), not the three
legitimate standalone single cards (Insights summary card, Run status card,
snapshot record) that the observability batch correctly left alone:

- ``_renderInsights``'s "Best sources" list (one ``.admin-card`` per source).
- ``_renderVariants`` (one ``.admin-card`` per resume variant).

Both are fixed here the same way, reusing the same existing CSS pair.

Each assertion below was verified, by hand, to actually go red when the
underlying fix is reverted (temporarily restore the pre-fix markup, rerun,
see the assertion fail, re-apply the fix) per the batch's test-coverage DoD.
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
JS_DIR = REPO_ROOT / "workspace" / "static" / "js"
STYLE_CSS = REPO_ROOT / "workspace" / "static" / "style.css"
DEBUG_JS = JS_DIR / "applicantDebug.js"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _top_level_fn(src: str, name: str) -> str:
    """Extract a top-level (unindented) `function name(...) { ... }` body.

    Same convention as ``test_applicant_round1_observability.py``: the
    function's own closing brace is the first line consisting of a bare "}"
    with NO leading whitespace.
    """
    m = re.search(rf"function {re.escape(name)}\([^)]*\)\s*\{{(.*?)\n\}}", src, re.S)
    assert m, f"expected a top-level function {name}(...) in the source"
    return m.group(1)


# ── #93: Sources/Tools toggle rows -> .applicant-debug-list-row ────────────


def test_sources_toggle_rows_use_list_row_not_admin_card():
    """Each source row inside `_renderSources` must use
    `.applicant-debug-list-row` (hairline-divided flat list) instead of a
    bordered `.admin-card` tile. The exploration-budget control above the
    list is a distinct standalone card and must be left as `.admin-card`."""
    src = _read(DEBUG_JS)
    fn = _top_level_fn(src, "_renderSources")
    assert 'class="applicant-debug-list-row"' in fn, (
        "expected the source toggle rows to use .applicant-debug-list-row"
    )
    # The old per-row bordered-tile pattern (admin-card carrying the row's own
    # flex layout inline) must be gone.
    assert 'class="admin-card" style="display:flex;justify-content:space-between;align-items:center;gap:10px;">' not in fn, (
        "found the old per-row .admin-card tile pattern still present"
    )
    # The exploration-budget card is a legitimate standalone card, not a list
    # row — it must still exist as its own .admin-card.
    assert '<div class="admin-card" style="margin-bottom:10px;">' in fn
    assert "Exploration budget" in fn
    # Toggle-switch markup and wiring must be unchanged.
    assert 'class="applicant-source-toggle"' in fn
    assert 'class="admin-switch"' in fn


def test_tools_toggle_rows_use_list_row_not_admin_card():
    """Each tool row inside `_renderTools` must use
    `.applicant-debug-list-row` instead of a bordered `.admin-card` tile."""
    src = _read(DEBUG_JS)
    fn = _top_level_fn(src, "_renderTools")
    assert 'class="applicant-debug-list-row"' in fn, (
        "expected the tool toggle rows to use .applicant-debug-list-row"
    )
    assert 'class="admin-card" style="display:flex;justify-content:space-between;align-items:center;gap:10px;">' not in fn, (
        "found the old per-row .admin-card tile pattern still present"
    )
    assert 'class="applicant-tool-toggle"' in fn
    assert 'class="admin-switch"' in fn


def test_sources_and_tools_functions_carry_no_admin_card_at_all():
    """Belt-and-braces: after the #93 fix, `_renderSources`/`_renderTools`
    must not reference `.admin-card` for their toggle rows — the only
    `.admin-card` left in `_renderSources` is the standalone exploration-
    budget control (asserted separately above); `_renderTools` must carry
    none at all."""
    src = _read(DEBUG_JS)
    tools_fn = _top_level_fn(src, "_renderTools")
    assert 'class="admin-card"' not in tools_fn, (
        "_renderTools has no standalone-card content, so it must not "
        "render any admin-card markup after the fix"
    )


def test_applicant_debug_list_row_css_already_supports_toggle_row_layout():
    """The pre-existing `.applicant-debug-list-row` rule (built for the
    Activity rows, #94) already provides `display:flex`, `align-items:center`,
    `justify-content:space-between` and `gap:10px` — exactly the inline flex
    styles the old per-row `.admin-card` toggle rows carried by hand. No new
    CSS / compatible variant is needed to host a trailing toggle switch."""
    css = _read(STYLE_CSS)
    rule = re.search(
        r"#applicant-debug-modal \.applicant-debug-list-row\s*\{([^}]*)\}", css
    )
    assert rule, "expected the #applicant-debug-modal .applicant-debug-list-row rule"
    body = rule.group(1)
    assert "display: flex" in body
    assert "align-items: center" in body
    assert "justify-content: space-between" in body
    assert "gap: 10px" in body
    # And the hairline divider comes from a sibling rule, not the row rule
    # itself carrying its own border/bg (that would recreate the tile look).
    assert "background" not in body
    assert re.search(
        r"#applicant-debug-modal \.applicant-debug-list-row\s*\{[^}]*border-bottom:\s*1px solid var\(--border\)",
        css,
    )


def test_sources_and_tools_still_pass_host_param_through_to_rows():
    """The #93 fix must not regress the host-param sub-hosting fix
    (`test_sources_tools_update_accept_a_host_param_instead_of_always_using_body`
    in the observability suite): both renderers must still write into `host`,
    not fall back to `_body()` when a host is supplied."""
    src = _read(DEBUG_JS)
    for fn_name in ("_renderSources", "_renderTools"):
        fn = _top_level_fn(src, fn_name)
        assert "host.innerHTML" in fn, f"{fn_name} must still render into its host param"


# ── #100: additional remaining admin-card-stacking instances ───────────────


def test_insights_best_sources_rows_use_list_row_not_admin_card():
    """`_renderInsights`'s "Best sources" list mapped one `.admin-card` tile
    per source — the same stacked-tile anti-pattern as the #93 Sources/Tools
    rows, missed by the batch's own "only Sources/Tools remain" claim. Fixed
    the same way. The summary/roles/exploration-budget cards above it are
    legitimate standalone single cards and must be untouched."""
    src = _read(DEBUG_JS)
    fn = _top_level_fn(src, "_renderInsights")
    assert 'class="applicant-debug-list-row" style="align-items:flex-start;">' in fn, (
        "expected the per-source rows to use .applicant-debug-list-row"
    )
    assert (
        'class="admin-card" style="display:flex;justify-content:space-between;align-items:flex-start;gap:10px;">'
        not in fn
    ), "found the old per-source .admin-card tile pattern still present"
    # The standalone cards must be unaffected.
    assert "Conversion so far" in fn and '<div class="admin-card">' in fn
    assert "Roles that convert" in fn
    # The rows must still be grouped in their own hairline-divided list box
    # (this function renders straight to _body(), unlike Sources/Tools which
    # are already hosted inside _renderConfig's own list box).
    assert '<div class="applicant-debug-list">' in fn


def test_variants_rows_use_list_row_not_admin_card():
    """`_renderVariants` mapped one `.admin-card` tile per resume variant —
    another stacked-tile instance of the same #100 pattern. Fixed the same
    way, with its own `.applicant-debug-list` wrapper box (this tab renders
    straight to `_body()`, so it owns its own list box, mirroring Activity/
    Logs)."""
    src = _read(DEBUG_JS)
    fn = _top_level_fn(src, "_renderVariants")
    assert 'class="applicant-debug-list-row"' in fn
    assert '<div class="admin-card">' not in fn, (
        "found the old per-variant .admin-card tile pattern still present"
    )
    assert '<div class="applicant-debug-list">' in fn
    # design-audit Top-25 #19 prepends an optional plain-language "use this
    # variant more" nudge (`${nudge}`) ahead of the same list wrapper — the
    # wrapper itself (and its ${rows} content) is unchanged.
    assert "_body().innerHTML = `${nudge}<div class=\"applicant-debug-list\">${rows}</div>`;" in fn


def test_no_remaining_stacked_admin_card_map_join_pattern_in_debug_js():
    """Belt-and-braces sweep: no `.map(...).join('')` in the whole file may
    still build a per-item `.admin-card` tile — that is precisely the
    stacked-tile pattern #93/#100 eliminate. (Standalone single cards built
    without `.map(...)` — Insights summary/roles/budget, Run status/controls,
    the snapshot record, offline/gated/error placeholders — are unaffected
    by this check and are correctly left as `.admin-card`.)"""
    src = _read(DEBUG_JS)
    for m in re.finditer(r"\.map\(\([^)]*\)\s*=>\s*\{(.*?)\n(?:\s*)\}\)\.join\(''\)", src, re.S):
        block = m.group(1)
        assert 'class="admin-card"' not in block, (
            f"found a .map(...).join('') block still building per-item .admin-card tiles: {block[:120]!r}"
        )
