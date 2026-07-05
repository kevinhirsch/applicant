"""Regression coverage for exhaustive-audit-pass-2 lens 01 (micro-interactions)
findings #11, #13, #19, #50, and #51, confined to
``static/js/applicantModelLadder.js`` (Settings -> Set up Applicant -> model
escalation ladder).

Follows the project convention (see e.g. ``test_applicant_model_ladder_lens11.py``):
every fact is read from the actual static file content via ``pathlib`` + regex —
no browser, no DOM, no real socket. Each assertion was hand-verified to go red
when the underlying fix is reverted (backup the file to /tmp, revert the
change, rerun, see the assertion fail, restore from the backup) per the
project's revert-verify convention.

Findings covered (see ``docs/design/audits/exhaustive2/01_micro_interactions.md``):
  * #11 — `_syncFromDOM` trimmed `base_url`/`model` but stored the API key raw;
    a key pasted with a trailing newline/space sealed as-is and failed auth
    later with no visible cause. The key is now `.trim()`-ed too.
  * #13 — `_remove` spliced a tier with no confirm even when it had a saved
    API key, permanently losing `api_key_ref` on the next save from a single
    mis-click. A level with a saved key now gets a danger-styled
    `styledConfirm`; a keyless level still removes in one click.
  * #19 — the ladder's API-key field had no show/hide toggle (unlike Vault's
    password fields). A per-row toggle button now mirrors
    `applicantVault.js`'s `_wireSecretToggles` pattern.
  * #50 — ↑/↓ reorder triggers a full `_render()` that rebuilds every row from
    scratch, destroying the focused button and dropping keyboard focus to
    `<body>`. The moved tier's row is now refocused after the re-render.
  * #51 — the ladder only had arrow-button reordering while `dragSort.js`
    (already used by models.js / sessions.js / the image editor's layer
    panel) shipped unused in the same tree. It is now wired onto a dedicated
    drag handle, scoped with `handleSelector` so it never hijacks clicks on
    the row's own inputs/buttons; the arrow buttons remain for keyboard users.
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
JS_DIR = REPO_ROOT / "workspace" / "static" / "js"
LADDER_JS = JS_DIR / "applicantModelLadder.js"
DRAGSORT_JS = JS_DIR / "dragSort.js"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _fn_body(js: str, signature_pattern: str) -> str:
    """Extract a top-level function body by its opening signature regex.

    Matches from the signature to the closing brace that starts a line (the
    same convention the lens-11 ladder test file uses), which is good enough
    for this file's flat, non-nested top-level functions.
    """
    m = re.search(signature_pattern + r"\s*\{(.*?)\n\}\n", js, re.DOTALL)
    assert m, f"expected a function matching {signature_pattern!r}"
    return m.group(1)


# ── #11: API key is trimmed before it's stored ───────────────────────────────


def test_sync_from_dom_trims_the_api_key():
    js = _read(LADDER_JS)
    body = _fn_body(js, r"function _syncFromDOM\(\)")
    assert "get('.ml-key').trim()" in body, (
        "expected the API-key field to be trimmed the same way base_url/model already are, "
        "so a pasted trailing space/newline doesn't silently break auth later"
    )
    # Guard against a regression where trimming is reintroduced ahead of the
    # assignment but the assignment itself reverts to the untrimmed getter.
    assert "const key = get('.ml-key').trim();" in body
    assert "_tiers[i].api_key = key;" in body


def test_base_url_and_model_are_still_trimmed_too():
    # Sanity: #11 is specifically that the key was the ONE untrimmed field —
    # make sure the pre-existing trims on its neighbors didn't regress.
    js = _read(LADDER_JS)
    body = _fn_body(js, r"function _syncFromDOM\(\)")
    assert "get('.ml-base').trim()" in body
    assert "get('.ml-model').trim()" in body


# ── #13: confirm before removing a level with a saved key ───────────────────


def test_remove_is_async_and_confirms_only_when_a_key_is_saved():
    js = _read(LADDER_JS)
    m = re.search(r"async function _remove\(i\)\s*\{(.*?)\n\}\n", js, re.DOTALL)
    assert m, "expected _remove(i) to be async so it can await a confirm dialog"
    body = m.group(1)
    assert "if (t._hasKey)" in body, (
        "expected the confirm to be gated on the tier actually having a saved key"
    )
    assert "uiModule.styledConfirm(" in body, (
        "expected the project's shared styled confirm dialog, not window.confirm"
    )
    assert "danger: true" in body, "removing a level with a saved key should read as a destructive action"
    # The splice must still happen unconditionally for a keyless row and only
    # after an affirmative confirm for a keyed one — i.e. splice comes after
    # the confirm block, not before it.
    confirm_idx = body.index("styledConfirm(")
    splice_idx = body.index("_tiers.splice(i, 1)")
    assert confirm_idx < splice_idx, "the confirm must gate the removal, not run after it"


def test_keyless_row_removal_is_not_blocked_by_the_new_confirm():
    js = _read(LADDER_JS)
    body = re.search(r"async function _remove\(i\)\s*\{(.*?)\n\}\n", js, re.DOTALL).group(1)
    # The confirm block must be inside the `if (t._hasKey)` branch — i.e. an
    # early return only happens on a declined confirm, never unconditionally.
    if_block = re.search(r"if \(t\._hasKey\)\s*\{(.*?)\n  \}\n", body, re.DOTALL)
    assert if_block, "expected the confirm to be scoped inside an `if (t._hasKey)` block"
    assert "return" in if_block.group(1), "declining the confirm must bail out of the removal"


def test_del_button_click_handler_disables_during_the_async_remove():
    js = _read(LADDER_JS)
    body = _fn_body(js, r"function _render\(offline\)")
    assert "await _remove(i)" in body, "expected the .ml-del click handler to await the now-async _remove"
    assert "b.disabled = true" in body, (
        "expected the clicked remove button to be disabled while a confirm may be pending, "
        "guarding against a double-fire"
    )


# ── #19: show/hide toggle on the ladder's API-key field ──────────────────────


def test_key_field_has_a_show_hide_toggle_button():
    js = _read(LADDER_JS)
    row_body = _fn_body(js, r"function _tierRowHTML\(t, i\)")
    assert 'class="ml-key-toggle cal-btn"' in row_body, (
        "expected a show/hide toggle button next to the API-key input"
    )
    assert 'type="password" class="settings-select ml-key"' in row_body, (
        "the key input must still start masked (type=password) by default"
    )
    assert "aria-pressed=\"false\"" in row_body, "expected the toggle to expose its pressed state for a11y"


def test_key_toggle_is_wired_and_flips_input_type_and_label():
    js = _read(LADDER_JS)
    m = re.search(r"function _wireKeyToggles\(\)\s*\{(.*?)\n\}\n", js, re.DOTALL)
    assert m, "expected a _wireKeyToggles() wiring function"
    body = m.group(1)
    assert "'.ml-key-toggle'" in body
    assert "input.type === 'password'" in body, "expected the toggle to check/flip the input's type attribute"
    assert "'text' : 'password'" in body or "\"text\" : \"password\"" in body
    assert "aria-pressed" in body, "expected the toggle to update aria-pressed when clicked"
    # Must actually be wired up during render, or the buttons in the DOM do nothing.
    render_body = _fn_body(js, r"function _render\(offline\)")
    assert "_wireKeyToggles();" in render_body


# ── #50: focus restore after a keyboard-driven reorder ───────────────────────


def test_move_restores_focus_to_the_moved_tier_after_rerender():
    js = _read(LADDER_JS)
    body = re.search(r"function _move\(i, delta\)\s*\{(.*?)\n\}\n", js, re.DOTALL)
    assert body, "expected a _move(i, delta) function"
    move_body = body.group(1)
    assert "const movedTier = _tiers[i];" in move_body, (
        "expected _move to remember the moved tier BY REFERENCE before swapping, "
        "since its index changes and re-render replaces the DOM"
    )
    # The restore call must happen AFTER _render, not before (focusing before
    # the rebuild would just focus a node that's about to be destroyed).
    render_idx = move_body.index("_render(false)")
    restore_idx = move_body.index("_restoreFocusForTier(movedTier)")
    assert render_idx < restore_idx, "focus must be restored AFTER the re-render replaces the row DOM"


def test_restore_focus_helper_finds_the_row_by_tier_identity_not_stale_index():
    js = _read(LADDER_JS)
    body = re.search(r"function _restoreFocusForTier\(tier, preferredSelectors\)\s*\{(.*?)\n\}\n", js, re.DOTALL)
    assert body, "expected a _restoreFocusForTier(tier, preferredSelectors) helper"
    helper_body = body.group(1)
    assert "_tiers.indexOf(tier)" in helper_body, (
        "must re-locate the tier's CURRENT index by identity after the swap, not reuse the old index"
    )
    assert "data-tier-row=" in helper_body, "expected the helper to look up the row via the rendered data-tier-row attribute"
    assert "el.focus()" in helper_body
    assert "!el.disabled" in helper_body, (
        "must skip a disabled control (e.g. an Up button on the now-topmost row) rather than "
        "calling focus() on something that can't take it"
    )


# ── #51: drag reorder wired onto the existing dragSort.js kit ───────────────


def test_dragsort_module_is_imported_and_reused_not_reimplemented():
    js = _read(LADDER_JS)
    assert re.search(r"import\s+dragSortModule\s+from\s+'\./dragSort\.js';", js), (
        "expected the ladder to import and reuse the existing dragSort.js kit, not reimplement drag logic"
    )
    assert DRAGSORT_JS.exists(), "the shared drag-sort module this test/feature depends on is missing"


def test_drag_handle_exists_in_each_row_and_is_decorative_only():
    js = _read(LADDER_JS)
    row_body = _fn_body(js, r"function _tierRowHTML\(t, i\)")
    handle_tag = re.search(r"<span class=\"ml-drag-handle\"[^>]*>", row_body)
    assert handle_tag, "expected a dedicated drag-handle element per row"
    assert 'aria-hidden="true"' in handle_tag.group(0), (
        "the drag handle is mouse/touch-only (arrows remain the keyboard path) and must not be "
        "exposed to assistive tech as an extra, non-operable control"
    )


def test_dragsort_is_enabled_with_a_handle_selector_scoped_to_the_rows_container():
    js = _read(LADDER_JS)
    body = re.search(r"function _wireDragReorder\(\)\s*\{(.*?)\n\}\n", js, re.DOTALL)
    assert body, "expected a _wireDragReorder() wiring function"
    wire_body = body.group(1)
    assert "dragSortModule.enable('ml-rows', '[data-tier-row]'" in wire_body, (
        "expected drag-sort to be scoped to the ladder's own rows container/selector"
    )
    assert "handleSelector: '.ml-drag-handle'" in wire_body, (
        "a handleSelector is required — dragSort's mouse path has no input/button exclusion of its own, "
        "so without scoping to a dedicated handle a plain click to focus a text field would start a drag instead"
    )
    assert "onReorder: _onDragReorder" in wire_body

    render_body = _fn_body(js, r"function _render\(offline\)")
    assert "_wireDragReorder();" in render_body, "the drag-sort wiring must actually run on every render"


def test_on_drag_reorder_rebuilds_tiers_from_the_dropped_dom_order_by_identity():
    js = _read(LADDER_JS)
    body = re.search(r"function _onDragReorder\(orderedEls\)\s*\{(.*?)\n\}\n", js, re.DOTALL)
    assert body, "expected an _onDragReorder(orderedEls) handler"
    handler_body = body.group(1)
    assert "_syncFromDOM()" in handler_body, (
        "must flush any in-flight field edits before reordering, or a drag could silently discard them"
    )
    assert "getAttribute('data-tier-row')" in handler_body, (
        "must map each dropped element back to its tier via the row's own (pre-drag) index attribute, "
        "not assume the new visual order already matches _tiers"
    )
    assert "_tiers = newTiers;" in handler_body
    assert "_markDirty();" in handler_body, "a drag reorder must mark the ladder dirty like the arrow buttons do"
    assert "_render(false);" in handler_body


def test_arrow_buttons_remain_for_keyboard_users_alongside_drag():
    # #51 explicitly keeps the arrows as the keyboard-operable path since
    # dragSort is mouse/touch-only — this must not have been removed.
    js = _read(LADDER_JS)
    row_body = _fn_body(js, r"function _tierRowHTML\(t, i\)")
    assert 'class="cal-btn ml-up"' in row_body
    assert 'class="cal-btn ml-down"' in row_body
