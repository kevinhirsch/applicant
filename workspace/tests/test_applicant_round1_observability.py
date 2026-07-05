"""Regression coverage for the §E Observability design-audit fix batch (items
85-103), confined to ``static/js/applicantDebug.js``, ``static/js/applicantCompare.js``
and ``static/js/applicantActivity.js`` (+ the CSS facts they depend on in
``static/style.css``, read-only reference).

Follows the convention of ``test_applicant_round1_chatmind.py`` /
``tests/bdd/steps/test_enh_uia11y_steps.py``: every fact is read from the actual
static file content via ``pathlib`` + regex — no browser, no DOM, no real socket.
All three modules under test do top-level ``document``/launcher-wiring work on
import (``_boot()`` runs at module scope), so — same as the chatmind precedent —
they are not importable under a bare ``node --input-type=module`` without a DOM
shim; hence the text/regex approach throughout.

Each assertion here was verified, by hand, to actually go red when the
underlying fix is reverted (revert source -> rerun -> see the assertion fail ->
restore via ``git checkout``) per the batch's test-coverage DoD.

Item #88 (raw-hex -> CSS-var colors + perpetual-pulse removal) is split: the
pulse-removal half is already covered by
``tests/bdd/steps/test_enh_uia11y_steps.py`` (``applicantPulse not in css``) and
is deliberately NOT duplicated here; the raw-hex-removal half (not covered
elsewhere) IS tested below.

Item #100 was believed out of scope per the batch instructions (folded into
#93/#94, no separate fix) — see the UPDATE below.

RESOLVED FINDING (was a critical bug at test-authoring time, fixed since):
Item #86 claims a new ``_renderConfig()`` hosts Sources/Tools/Update as
sub-sections of one Config pane. At authoring time, the ``TABS`` array was
correctly collapsed to 6 entries but ``_renderConfig`` was referenced at the
tab-dispatch map (`config: _renderConfig`) while never being defined anywhere
in the file — an undeclared-identifier reference in an object literal, which
throws a ``ReferenceError`` on evaluation, i.e. on every ``_renderTab()`` call
(every tab click, every modal open). This has since been fixed: ``_renderConfig``
now builds three named sub-section hosts (Sources/Tools/Update) and renders
``_renderSources``/``_renderTools``/``_renderUpdate`` into their own host
element each (using the ``host`` parameter + ``_needCampaignIn``/`_renderGated`/
`_renderOffline`'s pre-existing host-scoping support), so one section's
error/offline/gated state can't blank out its siblings. Tested below.

UPDATE — item #93 is now implemented (was NOT, at this file's original
authoring time — see the superseded paragraph this replaces, preserved in git
history): the fix above hosted the two Config sub-sections correctly, but the
individual toggle rows inside ``_renderSources``/``_renderTools`` still
rendered one ``.admin-card`` per row, unchanged, so no test for it was added
here (a real but separate, non-blocking cosmetic gap, deliberately left
un-covered pending the fix). Both rows now use the pre-existing
``.applicant-debug-list``/``.applicant-debug-list-row`` treatment (the same
pair ``_renderActivity``/``_renderLogs`` already use). Item #100 turned out
to have two more genuine remaining ``.admin-card``-stacking instances beyond
Sources/Tools (the Insights "Best sources" list and the Variants list), also
fixed the same way. All of this is covered in
``test_applicant_round1_remainder_debuglistrows.py`` (including the
revert-to-red verification for each converted row), which also confirms this
file's own #93/#94/#100-numbered tests below (e.g.
``test_activity_rows_use_list_row_with_demoted_secondary_action``) still pass
unregressed.
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
JS_DIR = REPO_ROOT / "workspace" / "static" / "js"
STYLE_CSS = REPO_ROOT / "workspace" / "static" / "style.css"
DEBUG_JS = JS_DIR / "applicantDebug.js"
COMPARE_JS = JS_DIR / "applicantCompare.js"
ACTIVITY_JS = JS_DIR / "applicantActivity.js"

_HAS_NODE = shutil.which("node") is not None


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _top_level_fn(src: str, name: str) -> str:
    """Extract a top-level (unindented) `function name(...) { ... }` body.

    Matches the chatmind precedent: the function's own closing brace is the
    first line consisting of a bare "}" with NO leading whitespace, which is
    safe here because every function body under test is itself indented.
    """
    m = re.search(rf"function {re.escape(name)}\([^)]*\)\s*\{{(.*?)\n\}}", src, re.S)
    assert m, f"expected a top-level function {name}(...) in the source"
    return m.group(1)


# ── #85: Debug active-tab underline scoped to a neutral token ──────────────

def test_debug_active_tab_border_is_scoped_neutral_override():
    """The Debug modal's active-tab underline used to inherit the shared
    `.admin-tab.active` rule's hued `--sys-blue` accent. A scoped override
    `#applicant-debug-modal .admin-tab.active` must set a neutral chrome-ink
    token instead, while the SHARED base rule (used by Library/Cookbook/
    Memory/Settings/Onboarding) stays untouched with `--sys-blue`."""
    css = _read(STYLE_CSS)
    scoped = re.search(r"#applicant-debug-modal\s+\.admin-tab\.active\s*\{([^}]*)\}", css)
    assert scoped, "expected a #applicant-debug-modal .admin-tab.active override in style.css"
    scoped_block = scoped.group(1)
    assert re.search(r"border-bottom-color:\s*var\(--chrome-ink", scoped_block), (
        "the Debug-scoped override must use a neutral chrome-ink token, not --sys-blue"
    )
    assert "--sys-blue" not in scoped_block, "the scoped override must not carry the hued accent"

    # The shared base rule (unscoped) must be left exactly as-is: still blue.
    base = re.search(r"(?<!#applicant-debug-modal )\.admin-tab\.active\s*\{([^}]*)\}", css)
    assert base, "expected the shared base .admin-tab.active rule to still exist"
    assert re.search(r"border-bottom-color:\s*var\(--sys-blue\)", base.group(1)), (
        "the shared base rule (other surfaces) must be untouched and keep --sys-blue"
    )


# ── #86: TABS collapsed from 8 to 6 (true part only — see module docstring) ─

def test_debug_tabs_array_collapsed_to_six_top_level_entries():
    """TABS must list exactly 6 top-level tabs — activity/insights/logs/
    variants/run/config — not the previous 8 (which had separate
    sources/tools/update top-level tabs)."""
    src = _read(DEBUG_JS)
    m = re.search(r"const TABS = \[(.*?)\n\];", src, re.S)
    assert m, "expected a top-level `const TABS = [...]` array"
    body = m.group(1)
    keys = re.findall(r"\[\s*'([a-z_]+)'\s*,", body)
    assert keys == ["activity", "insights", "logs", "variants", "run", "config"], (
        f"expected the 6-tab collapse, got {keys!r}"
    )
    # The old separate top-level tabs must not reappear as TABS entries.
    for old in ("sources", "tools", "update"):
        assert old not in keys, f"{old!r} must not be a standalone top-level tab anymore"


def test_render_config_is_defined_and_hosts_three_independent_sub_sections():
    """_renderConfig must be a real, declared function (not just referenced in
    the tab-dispatch map — a dangling reference there throws a ReferenceError
    on every _renderTab() call). It must build three separately-addressable
    host containers and render Sources/Tools/Update into their OWN host each
    (not all three sharing _body(), which would let one section's error state
    blank out its siblings)."""
    src = _read(DEBUG_JS)
    assert "config: _renderConfig," in src
    m = re.search(r"\nasync function _renderConfig\(\)\s*\{(.*?)\n\}\n", src, re.S)
    assert m, "expected a declared async function _renderConfig()"
    body = m.group(1)

    # Three distinct host containers, one per sub-section.
    for host_id in ("applicant-config-sources", "applicant-config-tools", "applicant-config-update"):
        assert f'id="{host_id}"' in body, f"expected a #{host_id} sub-section host"

    # Each renderer must be paired with its OWN host element (a sections
    # list/array, or literal calls — either way, each render fn must be
    # invoked with a real sub-host, never with no argument / _body()).
    for fn_name, host_var in (
        ("_renderSources", "sourcesHost"),
        ("_renderTools", "toolsHost"),
        ("_renderUpdate", "updateHost"),
    ):
        assert host_var in body, f"expected a {host_var} element captured from the sub-section markup"
        assert fn_name in body, f"expected {fn_name} to be referenced in _renderConfig"
    assert "renderFn(sectionHost)" in body or (
        "_renderSources(sourcesHost)" in body
        and "_renderTools(toolsHost)" in body
        and "_renderUpdate(updateHost)" in body
    ), "expected each renderer to be invoked with its own sub-host, not shared _body()"
    # _body() may appear once, to fetch the overall Config pane container that
    # the three sub-hosts live inside — but the three renderers themselves
    # must never be called bare (which would default them back to _body()).
    assert not re.search(r"_render(Sources|Tools|Update)\(\s*\)", body), (
        "_renderConfig must not call a sub-section renderer with no host arg "
        "(that would default it back to the shared _body())"
    )


def test_sources_tools_update_accept_a_host_param_instead_of_always_using_body():
    """The three sub-section renderers must be host-scoped (accept an optional
    host element, defaulting to _body() for their old top-level-tab callers),
    not hard-wired to _body() — otherwise _renderConfig's three sub-sections
    would all stomp on the same element."""
    src = _read(DEBUG_JS)
    for fn_name in ("_renderSources", "_renderTools", "_renderUpdate"):
        sig = re.search(rf"\nasync function {fn_name}\(([^)]*)\)", src)
        assert sig, f"expected an async function {fn_name}(...) declaration"
        assert "host" in sig.group(1), f"{fn_name} must accept a host parameter"

    # node --check confirms the file still parses cleanly with the host-scoped
    # signatures in place (a real syntax regression here would fail CI's own
    # front-end JS syntax gate too, but this keeps the check local to the fix).
    res = subprocess.run(["node", "--check", str(DEBUG_JS)], capture_output=True, text=True, timeout=15)
    assert res.returncode == 0, f"node --check failed:\n{res.stderr}"


# ── #87: header = leading picker + trailing single overflow; banner separate ─

def test_debug_header_row_has_leading_picker_and_trailing_overflow_only():
    """The header controls row must contain exactly the job-search picker
    (leading) and ONE overflow control (trailing, `margin-left:auto`) housing
    both former actions — not a packed picker+status+two-buttons row."""
    src = _read(DEBUG_JS)
    m = re.search(
        r'<div style="padding:8px 14px 0;display:flex;gap:10px;align-items:center;flex-wrap:wrap;">(.*?)</div>\s*\n\s*<div id="applicant-debug-engine-banner"',
        src, re.S,
    )
    assert m, "expected to find the header controls row"
    row = m.group(1)
    assert 'id="applicant-debug-campaign"' in row, "expected the leading job-search picker"
    assert 'margin-left:auto' in row, "expected the overflow control to sit trailing (margin-left:auto)"
    assert 'id="applicant-debug-overflow-btn"' in row
    assert 'id="applicant-debug-download-log"' in row
    assert 'id="applicant-debug-chat"' in row
    # No leftover header-row status/offline badge text mixed into this row.
    assert "Engine offline" not in row


def test_debug_engine_banner_is_its_own_element_not_header_badge():
    """The 'engine offline' note must live in its own banner element above the
    tab strip (`#applicant-debug-engine-banner`), populated by `_setEngineBanner`,
    not as a badge crowding the header controls row."""
    src = _read(DEBUG_JS)
    assert re.search(r'<div id="applicant-debug-engine-banner"[^>]*style="[^"]*display:none;"', src), (
        "expected a standalone, initially-hidden engine banner element"
    )
    fn = re.search(r"function _setEngineBanner\(modal, up\)\s*\{(.*?)\n\}", src, re.S)
    assert fn, "expected _setEngineBanner"
    assert "applicant-debug-engine-banner" in fn.group(1)
    assert "Engine offline" in fn.group(1)


def test_debug_overflow_menu_houses_both_former_header_actions():
    """The overflow popover (`#applicant-debug-overflow-menu`) must contain
    exactly the two former standalone actions — Download activity log and Ask
    the assistant — as its menu items."""
    src = _read(DEBUG_JS)
    m = re.search(r'id="applicant-debug-overflow-menu"[^>]*>(.*?)</div>\s*\n\s*</div>', src, re.S)
    assert m, "expected the overflow menu markup"
    menu = m.group(1)
    assert "Download activity log" in menu
    assert "Ask the assistant" in menu
    item_ids = re.findall(r'id="(applicant-debug-[a-z-]+)"', menu)
    assert item_ids == ["applicant-debug-download-log", "applicant-debug-chat"], (
        f"expected exactly the two former actions as menu items, got {item_ids!r}"
    )


# ── #88 (raw-hex half only — pulse removal covered by test_enh_uia11y_steps) ─

def test_status_chip_colors_use_css_vars_not_bare_raw_hex():
    """`_statusChip` must assign colors via `var(--color-success|warning|muted, ...)`
    (a system token, with a hex fallback INSIDE the var()), never a bare raw hex
    literal assigned directly to `color`."""
    src = _read(DEBUG_JS)
    fn = _top_level_fn(src, "_statusChip")
    assert re.search(r"color = 'var\(--color-warning", fn)
    assert re.search(r"color = 'var\(--color-success", fn)
    assert re.search(r"color = 'var\(--color-muted", fn)
    # A bare raw-hex assignment (the pre-fix pattern) must not appear.
    assert not re.search(r"color = '#[0-9a-fA-F]{3,6}'", fn), (
        "expected no bare raw-hex color assignment in _statusChip"
    )


# ── #89: Compare table renders inside a scoped result panel, no inline borders

def test_compare_table_wrapped_in_result_panel_element():
    """The diff table must be built inside a `.applicant-compare-result-panel`
    wrapper appended to the result container, not directly on the modal glass."""
    src = _read(COMPARE_JS)
    fn = re.search(r"function _renderResult\(container, data, kind, campaignId\)\s*\{(.*?)\n\}", src, re.S)
    assert fn, "expected _renderResult"
    body = fn.group(1)
    assert re.search(r"panel\.className\s*=\s*'applicant-compare-result-panel'", body)
    assert "panel.appendChild(table)" in body
    assert "container.appendChild(panel)" in body


def test_compare_table_cells_have_no_inline_border_styles():
    """Per-cell borders must come from the scoped stylesheet rules
    (`#applicant-compare-modal .applicant-compare-table th/td`), not inline
    `style="border...` attributes baked into the row markup."""
    src = _read(COMPARE_JS)
    fn = re.search(r"function _renderResult\(container, data, kind, campaignId\)\s*\{(.*?)\n\}", src, re.S)
    assert fn
    body = fn.group(1)
    # Precisely: no `<td` / `<th` markup carries a `style="` attribute with
    # `border` inside it (the old per-cell inline-border pattern).
    for cell_match in re.finditer(r"<t[dh][^>]*>", body):
        tag = cell_match.group(0)
        style_m = re.search(r'style="([^"]*)"', tag)
        if style_m:
            assert "border" not in style_m.group(1), (
                f"found inline border styling on a table cell: {tag!r}"
            )

    css = _read(STYLE_CSS)
    assert re.search(
        r"#applicant-compare-modal \.applicant-compare-table th,\s*\n"
        r"#applicant-compare-modal \.applicant-compare-table td\s*\{([^}]*border-bottom[^}]*)\}",
        css,
    ), "expected the scoped stylesheet rule to own the cell borders"


# ── #90: REAL BUG FIX — .ow-select must sit on the <select>, not a wrapper div

@pytest.mark.parametrize(
    "path,select_id",
    [
        (COMPARE_JS, "applicant-compare-kind"),
        (COMPARE_JS, "applicant-compare-campaign"),
        (DEBUG_JS, "applicant-debug-campaign"),
        (DEBUG_JS, "applicant-run-mode"),
    ],
)
def test_ow_select_class_sits_on_select_element_not_wrapper_div(path, select_id):
    """The kit CSS targets `select.ow-select` directly (not a wrapping div), so
    `class="ow-select"` must be on the `<select>` tag itself for every kind/
    campaign (Compare) and campaign/run-mode (Debug) picker."""
    src = _read(path)
    assert re.search(rf'<select id="{select_id}"[^>]*class="ow-select"', src), (
        f"expected class=\"ow-select\" directly on <select id=\"{select_id}\">"
    )
    # The old bug pattern: a div wrapper carrying the class instead.
    assert '<div class="ow-select">' not in src


def test_no_ow_select_wrapper_div_anywhere_in_either_file():
    """Belt-and-braces: neither file should contain the old
    `<div class="ow-select"><select>...` wrapping pattern at all."""
    for path in (COMPARE_JS, DEBUG_JS):
        src = _read(path)
        assert not re.search(r'<div[^>]*class="ow-select"', src), (
            f"found a div wrapping the ow-select class in {path.name}"
        )


# ── #91: Activity snapshot dot uses CSS vars (distinct from the strip dot) ──

def test_activity_snapshot_dot_uses_css_vars_not_accent_fallback():
    """`_renderSnapshot`'s Now/Next dot must use `var(--color-success, ...)` when
    live and `var(--color-muted, ...)` when paused — not the old
    `var(--accent,#3a8)`. This is the modal's OWN snapshot dot, distinct from
    the always-visible `.applicant-status-strip .applicant-status-dot`."""
    src = _read(ACTIVITY_JS)
    fn = re.search(r"function _renderSnapshot\(host, data\)\s*\{(.*?)\n\}", src, re.S)
    assert fn, "expected _renderSnapshot"
    body = fn.group(1)
    assert re.search(r"live \? 'var\(--color-success", body)
    assert re.search(r"var\(--color-muted", body)
    assert "--accent" not in body, "the snapshot dot must not use the old --accent token"
    assert "#3a8" not in body, "the old hardcoded accent fallback color must be gone"


# ── #92: sentence-case, no uppercase transform on snapshot labels/heading ───

def test_snapshot_labels_and_recently_heading_are_sentence_case():
    """`_snapshotLine` labels ('Now' / 'Up next') and the 'Recently I…' heading
    must render at 11px/weight 600 WITHOUT `text-transform: uppercase` — the
    whole file must carry no text-transform rule at all (it previously did, on
    exactly these two spots)."""
    src = _read(ACTIVITY_JS)
    assert "text-transform" not in src, "expected no text-transform anywhere in applicantActivity.js"

    line_fn = _top_level_fn(src, "_snapshotLine")
    assert re.search(r'font-size:11px;font-weight:600', line_fn), (
        "expected the label span to be 11px/weight 600"
    )
    assert "_snapshotLine('Now', now.sentence)" in src
    assert "_snapshotLine('Up next', next.sentence, extra)" in src

    heading_m = re.search(r"const heading = `(.*?)`;", src, re.S)
    assert heading_m, "expected the Recently-I heading template"
    heading = heading_m.group(1)
    assert "Recently I…" in heading
    assert "font-size:11px;font-weight:600" in heading


# ── #94: Activity rows -> list-row treatment; Details primary, mark-sub demoted

def test_activity_rows_use_list_row_with_demoted_secondary_action():
    """Each application row in `_renderActivity` must use
    `.applicant-debug-list-row` (hairline-divided flat list), with "Details"
    as the primary `.admin-btn-sm` action and "I submitted this" demoted to
    `.applicant-debug-row-secondary` (a plain text-style affordance)."""
    src = _read(DEBUG_JS)
    fn = re.search(r"async function _renderActivity\(token\)\s*\{(.*?)\n\}", src, re.S)
    assert fn, "expected _renderActivity"
    body = fn.group(1)
    assert 'class="applicant-debug-list-row"' in body
    assert re.search(r'class="applicant-debug-row-secondary applicant-debug-marksub"[^>]*>I submitted this<', body)
    assert re.search(r'class="admin-btn-sm applicant-debug-detail"[^>]*>Details<', body)
    assert '<div class="applicant-debug-list">' in body


# ── #95: Logs -> structured rows via _parseLogEntry + Download logs (.txt) ──

def test_parse_log_entry_extracts_time_level_message():
    """`_parseLogEntry` must split a raw entry into {time, level, message} for
    structured rendering, handling both object and formatted-string shapes."""
    src = _read(DEBUG_JS)
    fn = _top_level_fn(src, "_parseLogEntry")
    assert "time" in fn and "level" in fn and "message" in fn
    assert "toUpperCase()" in fn


def test_logs_tab_renders_structured_rows_and_download_button_not_copy():
    """Logs must render as `.applicant-debug-list-row`s (time / level chip /
    message), and offer a "Download logs" button producing a `.txt` blob — the
    old "Copy logs" affordance must be gone."""
    src = _read(DEBUG_JS)
    fn = _top_level_fn(src, "_renderLogs")
    assert 'class="applicant-debug-list-row"' in fn
    # lens 12 #35: rows are now built from entries.map(_parseLogEntry) (a wider
    # 500-entry fetch + client-side level/text filter), still structured-parsed.
    assert '_parseLogEntry' in fn
    assert 'id="applicant-logs-download"' in fn
    assert ">Download logs<" in fn
    assert "Copy logs" not in fn
    assert re.search(r"_downloadText\(raw, `applicant-logs-\$\{_campaignId \|\| 'engine'\}\.txt`\)", fn)


def test_download_text_produces_a_plain_text_blob():
    """`_downloadText` (backing the Logs Download button) must build a
    `text/plain` Blob, not JSON or an HTML data URI."""
    src = _read(DEBUG_JS)
    fn = _top_level_fn(src, "_downloadText")
    assert re.search(r"new Blob\(\[text\],\s*\{\s*type:\s*'text/plain'\s*\}\)", fn)


# ── #96: Compare "Comparing…" has Cancel; Update "Working…" has none ───────

def test_compare_loading_state_offers_abortable_cancel():
    """Compare's in-flight "Comparing…" state must render an inline Cancel
    button wired to `AbortController.abort()` — the compare POST is a plain,
    safely-interruptible request."""
    src = _read(COMPARE_JS)
    fn = _top_level_fn(src, "_loadingWithCancel")
    assert "Cancel" in fn
    run_fn = re.search(r"async function _runCompare\(\)\s*\{(.*?)\n\}", src, re.S)
    assert run_fn, "expected _runCompare"
    body = run_fn.group(1)
    assert "new AbortController()" in body
    assert "applicant-compare-cancel" in body
    assert "controller.abort()" in body


def test_update_working_state_has_no_cancel_affordance():
    """Update's "Working…" state must NOT offer a Cancel — the update trigger
    (backup + apply + restart) is not safely interruptible, unlike Compare's
    plain POST. (The pre-flight confirm dialog's own "Cancel" button is a
    separate, expected affordance — it aborts BEFORE the request starts; scope
    this check to the in-flight "Working…" state itself, i.e. everything from
    that textContent assignment onward.)"""
    src = _read(DEBUG_JS)
    fn = _top_level_fn(src, "_renderUpdate")
    assert "'Working…'" in fn
    working_idx = fn.index("'Working…'")
    in_flight = fn[working_idx:]
    assert "Cancel" not in in_flight
    assert "AbortController" not in in_flight


# ── #97: Compare diff rows get .applicant-compare-row-diff, not just opacity ─

def test_compare_differing_rows_get_diff_row_class():
    """A dimension row whose values actually differ across entities must carry
    `.applicant-compare-row-diff` (font-weight + subtle bg via stylesheet),
    driven by `_dimDiffers`, not merely dimmed via inline opacity."""
    src = _read(COMPARE_JS)
    assert re.search(r"function _dimDiffers\(dim, entityIds, values\)\s*\{", src)
    fn = re.search(r"function _renderResult\(container, data, kind, campaignId\)\s*\{(.*?)\n\}", src, re.S)
    assert fn
    body = fn.group(1)
    assert re.search(r"const differs = _dimDiffers\(dim, entityIds, values\);", body)
    assert re.search(r"class=\"\\?\$\{differs \? 'applicant-compare-row-diff' : ''\\?\}\"", body)

    css = _read(STYLE_CSS)
    diff_rule = re.search(r"#applicant-compare-modal \.applicant-compare-row-diff\s*\{([^}]*)\}", css)
    assert diff_rule, "expected the scoped .applicant-compare-row-diff stylesheet rule"


# ── #98: openApplicantDebugDetail deep-link, applications-only ─────────────

def test_open_applicant_debug_detail_is_exported():
    """`openApplicantDebugDetail(campaignId, appId)` must be exported from
    applicantDebug.js so another surface (Compare) can deep-link into a
    specific application's detail drill-in."""
    src = _read(DEBUG_JS)
    assert re.search(r"export async function openApplicantDebugDetail\(campaignId, appId\)\s*\{", src)
    assert "export { _renderSnapshot };" in src or "openApplicantDebugDetail" in src


def test_compare_open_in_activity_link_is_applications_only():
    """The "Open in Activity" column header link must only render for
    `kind === 'applications'` — postings have no reachable detail surface, so
    `canLink` must be a strict equality check against 'applications', not any
    truthy/kind-agnostic condition."""
    src = _read(COMPARE_JS)
    assert re.search(r"const canLink = kind === 'applications';", src), (
        "expected canLink to be strictly gated on kind === 'applications'"
    )
    assert "canLink ? `<button type=\"button\" class=\"applicant-compare-open-detail\"" in src
    assert "openApplicantDebugDetail(campaignId, id)" in src


# ── #99: Refresh -> icon-only button, same .close-btn treatment as Close ───

def test_activity_refresh_button_is_icon_only_close_btn_treatment():
    """The Activity modal's Refresh control must be icon-only (an inline SVG,
    `.close-btn` styling, `aria-label`), matching Close's treatment — not the
    old mixed text+'✖' button."""
    src = _read(ACTIVITY_JS)
    m = re.search(
        r'<button class="close-btn" id="applicant-activity-refresh"[^>]*>(.*?)</button>',
        src, re.S,
    )
    assert m, "expected the icon-only refresh button"
    inner = m.group(1)
    assert "<svg" in inner
    assert "✖" not in inner
    assert re.match(r"^\s*$", re.sub(r"<svg.*?</svg>", "", inner, flags=re.S)), (
        "the refresh button must contain only the SVG icon, no stray text"
    )
    assert 'aria-label="Refresh the activity feed"' in src


# ── #101: "Ask the assistant" gated on the chat module actually being present

def test_ask_assistant_menu_item_gated_on_chat_module_presence():
    """The overflow menu's "Ask the assistant" item's visibility must be
    computed from `window.applicantChatModule.openApplicantChat` actually being
    a function EACH TIME the menu opens, not shown unconditionally with a
    no-op-toast-on-click fallback."""
    src = _read(DEBUG_JS)
    overflow_click = re.search(
        r"overflowBtn\.addEventListener\('click', \(e\) => \{(.*?)\n    \}\);",
        src, re.S,
    )
    assert overflow_click, "expected the overflow button's click handler"
    body = overflow_click.group(1)
    assert "willOpen" in body
    assert re.search(
        r"const hasChat = !!\(window\.applicantChatModule && typeof window\.applicantChatModule\.openApplicantChat === 'function'\);",
        body,
    )
    assert "chatItem.style.display = hasChat ? '' : 'none';" in body


# ── #102: _statGrid helper for Insights summary + per-source stat lines ────

def test_stat_grid_helper_used_for_insights_summary_and_source_rows():
    """`_statGrid` (aligned key/value grid) must back BOTH the "Conversion so
    far" summary card and each source's Matched/Approved/Submitted line inside
    `_renderInsights` — not dot-joined prose."""
    src = _read(DEBUG_JS)
    assert re.search(r"function _statGrid\(pairs\)\s*\{", src)
    fn = re.search(r"async function _renderInsights\(\)\s*\{(.*?)\n\}", src, re.S)
    assert fn, "expected _renderInsights"
    body = fn.group(1)
    assert body.count("_statGrid([") == 2, (
        "expected _statGrid used exactly twice: the summary card and the per-source rows"
    )
    assert "['Matched', num(s.total_matched)]" in body
    assert "['Matched', num(src.matched)]" in body


# ── #103: literal ✖ replaced with SVG X icon, same .close-btn container ────

@pytest.mark.parametrize("path", [ACTIVITY_JS, COMPARE_JS, DEBUG_JS])
def test_no_literal_x_glyph_remains(path):
    """None of the three modals may contain the literal '✖' glyph anymore —
    every close affordance must be the SVG X icon."""
    src = _read(path)
    assert "✖" not in src, f"found a literal ✖ glyph in {path.name}"


@pytest.mark.parametrize(
    "path,close_id",
    [
        (ACTIVITY_JS, "applicant-activity-close"),
        (COMPARE_JS, "applicant-compare-close"),
    ],
)
def test_close_buttons_use_svg_icon_in_close_btn_container(path, close_id):
    """Every modal's Close control must be a `.close-btn` container with an
    inline `<svg>` X icon (line/line cross), not a text glyph."""
    src = _read(path)
    m = re.search(rf'class="close-btn" id="{close_id}"[^>]*>(.*?)</button>', src, re.S)
    assert m, f"expected the close button for {close_id}"
    inner = m.group(1)
    assert "<svg" in inner
    assert "line" in inner  # the X is drawn from two <line> elements


def test_debug_close_button_uses_close_svg_constant_with_x_icon():
    """applicantDebug.js factors its close icon into a shared `CLOSE_SVG`
    constant (interpolated via `${CLOSE_SVG}`) rather than inlining the markup
    — the Debug close button must reference that constant, and the constant
    itself must be a real SVG X icon (two crossing <line>s), not a text glyph."""
    src = _read(DEBUG_JS)
    m = re.search(r'class="close-btn" id="applicant-debug-close"[^>]*>(.*?)</button>', src, re.S)
    assert m, "expected the Debug close button"
    inner = m.group(1)
    assert "${CLOSE_SVG}" in inner
    assert "✖" not in inner
    const_m = re.search(r"const CLOSE_SVG = '(.*?)';", src)
    assert const_m, "expected a CLOSE_SVG constant"
    assert "<svg" in const_m.group(1)
    assert "line" in const_m.group(1)
