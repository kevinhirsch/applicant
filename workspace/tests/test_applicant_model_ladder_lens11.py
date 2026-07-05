"""Regression coverage for exhaustive-audit-pass-2 lens 11 (settings/config)
findings #9, #33, and #55, confined to
``static/js/applicantModelLadder.js`` (Settings -> Set up Applicant -> model
escalation ladder).

Follows the project convention (see e.g. ``test_applicant_campaign_clarity_lens11.py``
and ``test_applicant_settings_nav_lens11.py``): every fact is read from the actual
static file content via ``pathlib`` + regex — no browser, no DOM, no real socket.
Each assertion was hand-verified to go red when the underlying fix is reverted
(backup the file to /tmp, revert the change, rerun, see the assertion fail,
restore from the backup) per the project's revert-verify convention.

Findings covered (see ``docs/design/audits/exhaustive2/11_settings_config.md``):
  * #9 — tiers were free-text provider/URL/key/model rows with no way to pick
    an already-saved model connection and no per-tier way to check whether the
    address actually works. A tier now gets a "Pick a saved connection" select
    populated from the saved-connections list (the same list rendered lower on
    the page) plus a "Test this level" button that reuses the existing
    probe-without-saving route (`POST .../model-endpoints/test`) the saved
    connections list and admin.js's endpoint manager already call.
  * #33 — reorder/add/remove only mutated the in-memory tier list until
    "Save levels" was clicked, with no signal that there were unsaved edits.
    An "Unsaved changes" badge (mirroring the campaign-settings dirty
    indicator) now appears on any edit and clears after a successful save.
  * #55 — `context_window` silently defaulted to 8192 on a missing/unparseable
    stored value, and there was no autofill from what's actually known about a
    model. A small known-model table now autofills a real number when the
    model name is recognized, and the missing/unparseable case is explicitly
    labeled as a fallback rather than presented as a real value.
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
JS_DIR = REPO_ROOT / "workspace" / "static" / "js"
LADDER_JS = JS_DIR / "applicantModelLadder.js"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _fn_body(js: str, signature_pattern: str) -> str:
    """Extract a top-level function body by its opening signature regex.

    Matches from the signature to the closing brace that starts a line (the
    same convention the campaign-settings lens-11 test file uses), which is
    good enough for this file's flat, non-nested top-level functions.
    """
    m = re.search(signature_pattern + r"\s*\{(.*?)\n\}\n", js, re.DOTALL)
    assert m, f"expected a function matching {signature_pattern!r}"
    return m.group(1)


# ── #9: pick a saved connection into a tier + a per-tier Test control ───────


def test_connection_picker_select_populated_from_saved_endpoints():
    js = _read(LADDER_JS)
    body = _fn_body(js, r"function _connectionPickerHTML\(t, i\)")
    assert 'class="settings-select ml-connection"' in body, (
        "expected a select the tier row can use to pick a saved connection"
    )
    assert '<option value="">' in body, (
        "expected a manual-entry default option so picking a connection stays optional"
    )
    assert "_endpoints.map" in body, (
        "the picker's options must come from the same _endpoints list the "
        "saved-connections card below renders, not a separate/duplicated fetch"
    )


def test_connection_picker_is_rendered_inside_the_tier_row():
    js = _read(LADDER_JS)
    body = _fn_body(js, r"function _tierRowHTML\(t, i\)")
    assert "_connectionPickerHTML(t, i)" in body, (
        "each tier row must render the saved-connection picker, not just the free-text fields"
    )


def test_picking_a_connection_fills_provider_and_address_without_retyping():
    js = _read(LADDER_JS)
    body = _fn_body(js, r"function _wireTierEditing\(\)")
    assert "connEl.addEventListener('change'" in body, (
        "expected the connection select to be wired to a change handler"
    )
    assert "_guessProvider(ep.base_url, ep.category)" in body, (
        "picking a connection should fill in the provider from the saved endpoint"
    )
    assert "t.base_url = ep.base_url" in body, (
        "picking a connection should fill in the server address from the saved endpoint, "
        "instead of leaving the user to retype it"
    )
    assert "t._connectionModels" in body, (
        "picking a connection should carry over its already-probed model list "
        "(so the model field can offer them) rather than forcing a retyped model too"
    )


def test_connection_with_saved_key_gets_an_honest_note_instead_of_a_silent_gap():
    js = _read(LADDER_JS)
    body = _fn_body(js, r"function _tierRowHTML\(t, i\)")
    assert "_connectionHasKey" in body, (
        "expected the tier row to know whether the picked connection has a saved key"
    )
    # The key itself is never sent to the browser (security boundary already used
    # by the saved-connections list), so the UI must say so rather than silently
    # leaving the key field blank with no explanation.
    assert "copy automatically" in js and "stays sealed" in js, (
        "expected an explicit note that a saved connection's key can't be auto-copied into the tier"
    )


def test_per_tier_test_button_exists_and_calls_the_existing_probe_route():
    js = _read(LADDER_JS)
    row_body = _fn_body(js, r"function _tierRowHTML\(t, i\)")
    assert 'class="cal-btn ml-test"' in row_body, "expected a per-tier Test control"
    assert "Test this level" in row_body

    wire_body = _fn_body(js, r"function _wireTierEditing\(\)")
    assert "testBtn.addEventListener('click'" in wire_body
    assert "/model-endpoints/test" in wire_body, (
        "the per-tier Test button must reuse the existing probe-without-saving "
        "route, not a new/duplicated endpoint"
    )
    assert "new FormData()" in wire_body, (
        "the test route takes Form fields (base_url/api_key), matching the "
        "existing saved-connections + admin.js pattern, not a JSON body"
    )


# ── #33: dirty indicator on the ladder ──────────────────────────────────────


def test_dirty_badge_element_exists_hidden_by_default_when_clean():
    js = _read(LADDER_JS)
    body = _fn_body(js, r"function _render\(offline\)")
    assert 'id="ml-dirty-badge"' in body
    assert "memory-badge" in body, "expected the dirty badge to reuse the existing memory-badge design-system class"
    assert "Unsaved changes" in body
    # The badge's visibility must depend on the live _dirty flag, not be
    # hardcoded hidden/shown, so it also survives a re-render after an edit
    # (e.g. reordering a tier) without losing the "still dirty" state.
    assert "_dirty ? '' : 'display:none;'" in body or "_dirty ? '' : 'display:none'" in body, (
        "expected the badge's initial display style to be driven by the _dirty flag"
    )


def test_mark_dirty_helper_flips_the_badge_visible():
    js = _read(LADDER_JS)
    m = re.search(r"function _markDirty\(\)\s*\{(.*?)\n\}\n", js, re.DOTALL)
    assert m, "expected a _markDirty() helper (mirrors the campaign-settings _setDirty pattern)"
    body = m.group(1)
    assert "_dirty = true" in body
    assert "ml-dirty-badge" in body
    assert "badge.style.display = ''" in body


def test_edits_add_remove_and_reorder_all_mark_dirty():
    js = _read(LADDER_JS)
    add_body = _fn_body(js, r"function _tierRowHTML\(t, i\)")  # sanity: file parses to here
    assert add_body  # not empty

    move_body = re.search(r"function _move\(i, delta\)\s*\{(.*?)\n\}\n", js, re.DOTALL)
    assert move_body and "_markDirty()" in move_body.group(1), (
        "reordering a tier (move up/down) must mark the ladder dirty"
    )
    remove_body = re.search(r"function _remove\(i\)\s*\{(.*?)\n\}\n", js, re.DOTALL)
    assert remove_body and "_markDirty()" in remove_body.group(1), (
        "removing a tier must mark the ladder dirty"
    )
    render_body = _fn_body(js, r"function _render\(offline\)")
    assert "_markDirty()" in render_body, "adding a new tier level must mark the ladder dirty"

    wire_body = _fn_body(js, r"function _wireTierEditing\(\)")
    assert wire_body.count("_markDirty()") >= 3, (
        "provider/address/key/model field edits within a tier row must all mark the ladder dirty"
    )


def test_dirty_flag_clears_on_successful_save_and_on_fresh_mount():
    js = _read(LADDER_JS)
    save_body = re.search(r"async function _save\(\)\s*\{(.*?)\n\}\n", js, re.DOTALL)
    assert save_body, "expected an async _save() function"
    body = save_body.group(1)
    save_idx = body.index("_dirty = false")
    put_idx = body.index("_put(")
    assert save_idx > put_idx, (
        "the dirty flag must only clear AFTER the save request succeeds, "
        "never optimistically before it — a failed save must leave the badge showing"
    )

    mount_body = re.search(r"export function mountModelLadder\(host\)\s*\{(.*?)\n\}\n", js, re.DOTALL)
    assert mount_body and "_dirty = false" in mount_body.group(1), (
        "mounting the ladder fresh (e.g. reopening Settings) must start with a clean dirty state"
    )


# ── #55: context-window autofill + honest fallback labeling ─────────────────


def test_known_context_window_table_and_lookup_exist():
    js = _read(LADDER_JS)
    assert re.search(r"_KNOWN_CONTEXT_WINDOWS\s*=\s*\{", js), (
        "expected a known-model context-window table (ported from the workspace's "
        "own src/model_context.py KNOWN_CONTEXT_WINDOWS pattern)"
    )
    # A couple of concrete, easy-to-break entries so a hollowed-out table still fails.
    assert "'claude-3-5-sonnet': 200000" in js
    assert "'gpt-4o': 128000" in js

    lookup_body = re.search(r"function _lookupKnownContext\(model\)\s*\{(.*?)\n\}\n", js, re.DOTALL)
    assert lookup_body, "expected a _lookupKnownContext(model) helper"
    assert "_KNOWN_CONTEXT_WINDOWS" in lookup_body.group(1)


def test_missing_or_unparseable_stored_value_is_marked_as_fallback_not_a_real_value():
    js = _read(LADDER_JS)
    load_body = re.search(r"async function _load\(\)\s*\{(.*?)\n\}\n", js, re.DOTALL)
    assert load_body, "expected an async _load() function"
    body = load_body.group(1)
    assert "isFallback" in body, "expected the load path to explicitly compute a fallback flag"
    assert "_ctxFallback: isFallback" in body
    # The 8192 fallback must only be used when the flag says so, not unconditionally.
    assert "isFallback ? 8192" in body

    note_body = re.search(r"function _ctxNoteText\(t\)\s*\{(.*?)\n\}\n", js, re.DOTALL)
    assert note_body, "expected a _ctxNoteText(t) helper"
    note = note_body.group(1)
    assert "_ctxFallback" in note and "_ctxKnown" in note, (
        "the note must distinguish the fallback case from the known-autofill case"
    )
    assert "safe fallback (8192)" in note, (
        "the fallback case must be labeled in the UI as a fallback, not presented as a real number"
    )


def test_recognized_model_name_autofills_context_window_without_overriding_manual_edits():
    js = _read(LADDER_JS)
    wire_body = _fn_body(js, r"function _wireTierEditing\(\)")
    assert "_lookupKnownContext(t.model)" in wire_body, (
        "typing/picking a model must look up the known-context table"
    )
    assert "if (t._ctxManual) return;" in wire_body, (
        "a manually-set context window must never be silently overwritten by the autofill"
    )
    assert "t._ctxKnown = true" in wire_body and "ctxEl.value = String(known)" in wire_body, (
        "a recognized model must actually populate the visible context-window input, not just internal state"
    )
    # Editing the context field directly must flip it to "manual" so future
    # model edits stop overriding the user's own number.
    assert "ctxEl.addEventListener('input'" in wire_body
    assert "t._ctxManual = true" in wire_body
