"""Regression coverage for the accessibility-deep (05) and micro-interactions
(01) exhaustive2 audit findings implemented on the Settings shell and Debug
front-door surfaces only (``static/js/settings.js``,
``static/js/applicantDebug.js``).

Follows the convention of ``test_applicant_a11y_micro_chatmindvaultremote.py``
(the sibling pass over Chat/Mind/Vault/Remote): every fact is read from the
actual static file content via ``pathlib`` + regex — no browser, no DOM, no
real socket (these modules do top-level ``document``/``fetch`` work on
import, so they are not importable under a bare ``node --input-type=module``).

Each assertion here was verified, by hand, to go red when the underlying fix
is reverted (file-copy backup -> restore the old code -> rerun -> see the
assertion fail -> reapply the fix -> rerun green) per the batch's
test-coverage DoD; the backups used for that are NOT committed (only the
source fixes + this test file are).

Findings intentionally left unfixed on these two surfaces (out of this pass's
hard file scope — ``settings.js`` / ``applicantDebug.js`` only, no other
``.js``, no ``style.css``, no ``.html``, no Python):
  * the shared ``loadingHTML``/``errorHTML`` live-region kit-level fix
    (``applicantCore.js``);
  * the focus-trap's invisible-focusables / iframe hardening and
    ``styledConfirm``/``styledPrompt`` dialog semantics (``ui.js``);
  * Debug's overflow-menu arrow-key navigation (its two items are already
    real, natively Tab-reachable ``<button role="menuitem">``s — low value
    for the added complexity);
  * new CSS for a visually-hidden utility class — the two live regions added
    here (Debug's ``#applicant-debug-live``, and reusing existing message
    spans in Settings) use inline styles / existing elements instead, per
    this pass's "reuse existing CSS classes only" constraint.
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
JS_DIR = REPO_ROOT / "workspace" / "static" / "js"
SETTINGS_JS = JS_DIR / "settings.js"
DEBUG_JS = JS_DIR / "applicantDebug.js"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _balanced_braces(js: str) -> bool:
    return js.count("{") == js.count("}")


def _top_level_fn(src: str, name: str) -> str:
    """Extract a top-level (unindented) `function name(...) { ... }` body —
    same convention as ``test_applicant_round1_remainder_debuglistrows.py``."""
    m = re.search(rf"function {re.escape(name)}\([^)]*\)\s*\{{(.*?)\n\}}", src, re.S)
    assert m, f"expected a top-level function {name}(...) in the source"
    return m.group(1)


# ── brace-balance sanity (both files) ───────────────────────────────────────


def test_both_files_stay_brace_balanced():
    for path in (SETTINGS_JS, DEBUG_JS):
        js = _read(path)
        assert _balanced_braces(js), f"{path.name} has unbalanced braces"


# ── Debug (applicantDebug.js) ────────────────────────────────────────────────


def test_debug_reinits_focus_management_on_every_open_not_just_first_creation():
    """a11y-deep #1: Debug is one of the six modals the audit names explicitly
    as losing all focus management after its first close, because the
    initModalA11y wiring lived inside `_ensureModalEl`'s "already built"
    early-return guard. Fixed by moving the wiring into a `_wireA11y()`
    helper called fresh from every open path."""
    js = _read(DEBUG_JS)
    m = re.search(r"function _ensureModalEl\(\)\s*\{(.*?)\n\}\n", js, re.DOTALL)
    assert m, "expected _ensureModalEl's body"
    assert "uiModule.initModalA11y(" not in m.group(1), (
        "the initModalA11y call must not live in the one-time creation path any more"
    )

    m2 = re.search(r"function _wireA11y\(modal\)\s*\{(.*?)\n\}\n", js, re.DOTALL)
    assert m2, "expected a _wireA11y(modal) helper"
    assert "uiModule.initModalA11y(modal," in m2.group(1)

    for opener in ("openApplicantDebug", "openApplicantDebugDetail"):
        m3 = re.search(rf"export async function {opener}\([^)]*\)\s*\{{(.*?)\n\}}\n", js, re.DOTALL)
        assert m3, f"expected {opener}'s body"
        assert "_wireA11y(modal)" in m3.group(1), f"{opener} must (re)wire a11y on every open"


def test_debug_modal_named_via_labelledby_not_a_hardcoded_string():
    """a11y-deep #9: point the dialog's accessible name at its own visible
    heading instead of a hardcoded aria-label string that can drift."""
    js = _read(DEBUG_JS)
    assert 'id="applicant-debug-title"' in js
    assert "modal.setAttribute('aria-label', 'Applicant diagnostics')" not in js


def test_debug_tabs_have_real_tab_semantics():
    """a11y-deep #29: Debug's tab strip toggled `.active` with no
    role="tab"/"tablist"/"tabpanel" or aria-selected — SR users heard
    undifferentiated buttons with no selected state."""
    js = _read(DEBUG_JS)
    assert 'id="applicant-debug-tabs" role="tablist"' in js
    m = re.search(r"\$\{TABS\.map\(\(\[k, label\], i\) => `(.*?)`\)\.join", js, re.DOTALL)
    assert m, "expected the tab-button template"
    tpl = m.group(1)
    assert 'role="tab"' in tpl
    assert "aria-selected=" in tpl
    assert 'aria-controls="applicant-debug-body"' in tpl
    assert 'id="applicant-debug-tab-${k}"' in tpl
    assert 'id="applicant-debug-body" role="tabpanel"' in js


def test_debug_tab_activation_keeps_active_class_aria_selected_and_labelledby_in_sync():
    """The three places that change the active tab (click, arrow-key nav, and
    the Compare deep-link's Activity-tab jump) must all go through the same
    sync helper so `.active`, `aria-selected` and the panel's
    `aria-labelledby` can never drift apart."""
    js = _read(DEBUG_JS)
    sync_body = _top_level_fn(js, "_syncTabActiveUI")
    assert "classList.toggle('active', active)" in sync_body
    assert "setAttribute('aria-selected', active ? 'true' : 'false')" in sync_body
    assert "body.setAttribute('aria-labelledby', x.id)" in sync_body

    activate_body = _top_level_fn(js, "_activateTab")
    assert "_syncTabActiveUI(tab)" in activate_body
    assert "_renderTab()" in activate_body

    # the click handler and the arrow-key handler both call _activateTab
    assert "b.addEventListener('click', () => { _activateTab(b.dataset.tab); });" in js
    assert "_activateTab(next.dataset.tab);" in js
    # the deep-link jump uses the no-render sync variant (it calls _renderTab
    # itself right after, so activating twice would double-fetch)
    assert "_syncTabActiveUI('activity');" in js


def test_debug_tablist_has_arrow_key_navigation():
    """micro-interactions/a11y-deep #29: no tab strip in the product had
    arrow-key nav. Additive — must not touch any tab button's tabindex, so
    the existing Tab-key order through the strip is unchanged."""
    js = _read(DEBUG_JS)
    assert "tablist.addEventListener('keydown'" in js
    assert "'ArrowRight'" in js and "'ArrowLeft'" in js
    assert ".tabIndex" not in js.split("tablist.addEventListener")[0].split("const tablist")[-1]


def test_debug_source_and_tool_toggles_have_accessible_names():
    """a11y-deep #52: the per-source/per-tool kill-switch checkboxes wrapped
    only an empty `<span class="admin-slider">` inside their `<label>` — AT
    heard "checkbox, checked" with no subject."""
    js = _read(DEBUG_JS)
    sources_fn = _top_level_fn(js, "_renderSources")
    assert 'aria-label="Turn ${esc(s.source_key)} on or off"' in sources_fn
    tools_fn = _top_level_fn(js, "_renderTools")
    assert 'aria-label="Turn ${esc(label)} on or off"' in tools_fn
    # lens 12 #10: the exploration-budget control is now percent-based (0-100),
    # matching Campaign Settings — the accessible name tracks the same units.
    assert 'aria-label="Exploration budget, a percentage between 0 and 100"' in sources_fn


def test_debug_source_and_tool_toggles_disable_during_their_round_trip():
    """micro-interactions — busy/disabled affordance: a fast double-toggle
    must not fire two overlapping PUT/POST requests against the same key."""
    js = _read(DEBUG_JS)
    sources_fn = _top_level_fn(js, "_renderSources")
    assert "cb.disabled = true;" in sources_fn and "cb.disabled = false;" in sources_fn
    tools_fn = _top_level_fn(js, "_renderTools")
    assert "cb.disabled = true;" in tools_fn and "cb.disabled = false;" in tools_fn


def test_debug_drilldown_close_restores_focus_to_the_details_button():
    """a11y-deep #6: the Details drill-in's own innerHTML swap destroyed the
    just-clicked Close button (and everything else in the panel), dropping
    keyboard focus to `<body>` with no way back in via Tab."""
    js = _read(DEBUG_JS)
    m = re.search(r"async function _showAppDetail\(appId, triggerBtn\)\s*\{(.*?)\n\}\n", js, re.DOTALL)
    assert m, "expected _showAppDetail(appId, triggerBtn)"
    body = m.group(1)
    assert "host._applicantDebugTrigger = triggerBtn;" in body
    assert "const trigger = host._applicantDebugTrigger;" in body
    assert "if (trigger && document.body.contains(trigger)) trigger.focus();" in body
    # the row's Details button must pass itself through
    assert "_showAppDetail(b.dataset.app, b)" in js


def test_debug_screenshot_thumbnails_are_keyboard_operable():
    """a11y-deep lens 01/05: the thumbnail was a bare click-only `<img>` with
    no tabindex/role and no Enter/Space handler."""
    js = _read(DEBUG_JS)
    m = re.search(r'<img class="applicant-debug-shot-thumb"[^`]*?/>`;', js, re.DOTALL)
    assert m, "expected the screenshot thumbnail template"
    tag = m.group(0)
    assert 'tabindex="0"' in tag
    assert 'role="button"' in tag
    assert "aria-label=" in tag
    assert "img.addEventListener('keydown'" in js
    assert "e.key !== 'Enter' && e.key !== ' '" in js


def test_debug_screenshot_lightbox_has_dialog_semantics_and_restores_focus():
    js = _read(DEBUG_JS)
    fn = re.search(r"function _openScreenshotLightbox\(url, label, triggerEl\)\s*\{(.*?)\n\}\n", js, re.DOTALL)
    assert fn, "expected _openScreenshotLightbox(url, label, triggerEl)"
    body = fn.group(1)
    assert "overlay.setAttribute('role', 'dialog')" in body
    assert "overlay.setAttribute('aria-modal', 'true')" in body
    assert "if (triggerEl && document.body.contains(triggerEl)) triggerEl.focus();" in body


def test_debug_tab_body_has_a_live_status_announcement():
    """a11y-deep #11/#12: outside `#toast`, Debug had zero live regions — a
    tab switch's loading/error/settled transition was inaudible."""
    js = _read(DEBUG_JS)
    assert '<div id="applicant-debug-live" aria-live="polite"' in js
    render_tab = _top_level_fn(js, "_renderTab")
    assert "setAttribute('aria-busy', 'true')" in render_tab
    assert "setAttribute('aria-busy', 'false')" in render_tab
    assert "_announce(`Loading ${tabLabel}" in render_tab
    assert "_announce(`${tabLabel} loaded.`)" in render_tab
    assert "_announce(`Could not load ${tabLabel}.`)" in render_tab


# ── Settings (settings.js) ───────────────────────────────────────────────────


def test_settings_modal_gets_dialog_role_and_focus_trap_on_every_open():
    """The Settings modal had NO focus management at all before this pass —
    no role="dialog"/aria-modal, no initModalA11y anywhere, so it never
    trapped focus, moved focus in, or restored it on close. Wired via
    `_wireDialogRole()` (attributes, once) + `initModalA11y` re-armed on
    every `open()` call (not gated behind a "first open" check)."""
    js = _read(SETTINGS_JS)
    dialog_fn = _top_level_fn(js, "_wireDialogRole")
    assert "modalEl.setAttribute('role', 'dialog')" in dialog_fn
    assert "modalEl.setAttribute('aria-modal', 'true')" in dialog_fn
    assert "modalEl.setAttribute('aria-labelledby', titleEl.id)" in dialog_fn

    open_fn = re.search(r"export function open\(tab\)\s*\{(.*?)\n\}\n", js, re.DOTALL)
    assert open_fn, "expected open(tab)'s body"
    assert "uiModule.initModalA11y(modalEl, _escapeClose)" in open_fn.group(1)

    close_fn = re.search(r"export function close\(\)\s*\{(.*?)\n\}\n", js, re.DOTALL)
    assert close_fn, "expected close()'s body"
    assert "_modalA11yCleanup();" in close_fn.group(1)

    assert "_wireDialogRole();" in _top_level_fn(js, "initAll")


def test_settings_escape_still_prefers_closing_an_open_inner_form():
    """The pre-existing "ESC mid-edit closes just the inner form, not the
    whole modal" footgun-guard must survive the refactor into
    initModalA11y's closeFn contract (previously a bespoke
    `document.keydown` listener)."""
    js = _read(SETTINGS_JS)
    escape_fn = _top_level_fn(js, "_escapeClose")
    assert "#unified-intg-form, #set-email-accounts-form" in escape_fn
    assert "close();" in escape_fn
    # the old duplicate document-level Escape listener must be gone
    close_block = _top_level_fn(js, "initClose")
    assert "document.addEventListener('keydown'" not in close_block


def test_settings_sidebar_tabs_have_real_tab_semantics_and_arrow_nav():
    """Same class of gap as Debug's tab strip (a11y-deep #29), applied to the
    Settings shell's own vertical sidebar nav — additive: no tabindex is
    changed, so plain Tab-key order through the nav is unchanged; Up/Down are
    a layered-on accelerator."""
    js = _read(SETTINGS_JS)
    wire_fn = _top_level_fn(js, "_wireTabSemantics")
    assert "sidebar.setAttribute('role', 'tablist')" in wire_fn
    assert "sidebar.setAttribute('aria-orientation', 'vertical')" in wire_fn
    assert "btn.setAttribute('role', 'tab')" in wire_fn
    assert "panel.setAttribute('role', 'tabpanel')" in wire_fn
    assert "panel.setAttribute('aria-labelledby', btn.id)" in wire_fn
    assert "'ArrowDown'" in wire_fn and "'ArrowUp'" in wire_fn
    assert "next.click();" in wire_fn

    sync_fn = _top_level_fn(js, "_syncTabAria")
    assert "aria-selected" in sync_fn

    # both places that toggle `.active` on the tab buttons must resync ARIA
    click_handler = _top_level_fn(js, "initTabs")
    assert "_syncTabAria();" in click_handler
    open_fn = re.search(r"export function open\(tab\)\s*\{(.*?)\n\}\n", js, re.DOTALL)
    assert "_syncTabAria();" in open_fn.group(1)


def test_settings_own_inline_forms_have_label_for_associations():
    """Same mechanical gap as the audit's #48 (sibling `<label>` with no
    `for=`) — here fixed for settings.js's OWN inline forms (email account,
    unified-integrations API/CalDAV/CardDAV/MCP/Vault), not the wizard's
    (that's applicantOnboarding.js, out of this pass's file scope)."""
    js = _read(SETTINGS_JS)
    orphaned = re.findall(r'<label class="settings-label">(?!\s)', js)
    # every `<label class="settings-label">` occurrence must now carry a
    # `for=` — a bare, unassociated one is a regression.
    assert not orphaned, f"found {len(orphaned)} settings-label(s) with no for="

    total = len(re.findall(r'<label class="settings-label"', js))
    with_for = len(re.findall(r'<label class="settings-label" for="', js))
    assert total == with_for and total >= 40, (
        f"expected every settings-label ({total}) to carry a for= ({with_for} do)"
    )

    # spot-check a representative sample actually points at its sibling control
    assert '<label class="settings-label" for="eaf-imap-host">Host' in js
    assert '<label class="settings-label" for="uf-smtp-same">Same as IMAP' in js
    assert '<label class="settings-label" for="uf-type-picker">Type</label>' in js


def test_settings_admin_switch_checkboxes_get_a_name_from_their_settings_label():
    """The STARTTLS/"Same as IMAP"/Default switches wrap only an empty
    `<span class="admin-slider">` — same unnamed-checkbox shape as Debug's
    source/tool toggles (a11y-deep #52). Fixed here via the `for=` sweep
    above (a `for=` label pointing at a checkbox still names it even though
    the checkbox also sits inside its own empty wrapping `<label
    class="admin-switch">`)."""
    js = _read(SETTINGS_JS)
    for cb_id in ("eaf-imap-starttls", "eaf-smtp-same", "uf-imap-starttls", "uf-smtp-same", "uf-email-default"):
        assert f'for="{cb_id}"' in js, f"expected a label[for={cb_id}] naming this switch"


def test_settings_reduced_motion_gates_the_test_connection_success_glow():
    """design-audit #45's "reduced-motion coverage is genuinely good — keep
    it audited": the email-account Test-connection button's success state
    set an ungated `infinite`-duration CSS animation with no OS-preference
    check anywhere in JS (`prefers-reduced-motion` cannot reach an inline
    `style.animation` assignment via CSS alone)."""
    js = _read(SETTINGS_JS)
    prm_fn = _top_level_fn(js, "_prefersReducedMotion")
    assert "prefers-reduced-motion: reduce" in prm_fn
    assert "if (!_prefersReducedMotion()) btn.style.animation = 'cookbook-srv-glow-ok 2.4s ease-in-out infinite';" in js


def test_settings_message_spans_are_wired_as_live_regions():
    """a11y-deep #11/#12: "Saved" / "Failed to save" / a Test-connection
    result reached only sighted users — none of the ~20 inline status spans
    (`set-defaultChatMsg`, `uf-email-msg`, etc.) were live regions."""
    js = _read(SETTINGS_JS)
    wire_fn = _top_level_fn(js, "_wireLiveStatusRegions")
    assert "setAttribute('aria-live', 'polite')" in wire_fn
    assert "MutationObserver" in wire_fn
    assert "_wireLiveStatusRegions();" in _top_level_fn(js, "initAll")


def test_settings_search_provider_picker_is_keyboard_operable():
    """micro-interactions lens 01 / a11y-deep lens 05 keyboard-operability:
    the logo-picker popover's `.adm-provider-item` options were click-only —
    no tabindex, no Enter/Space to choose, no arrow-key nav, no Escape."""
    js = _read(SETTINGS_JS)
    assert "pickerMenu.setAttribute('role', 'listbox');" in js
    assert 'tabindex="0" aria-selected=' in js
    assert "pickerBtn.setAttribute('aria-haspopup', 'listbox');" in js

    choose_fn = _top_level_fn(js, "_chooseSearchPickerItem")
    assert "provSel.dispatchEvent(new Event('change'" in choose_fn
    assert "pickerBtn.focus();" in choose_fn

    m = re.search(r"pickerMenu\.addEventListener\('keydown', function\(e\)\s*\{(.*?)\n    \}\);", js, re.DOTALL)
    assert m, "expected the picker menu's keydown handler"
    kb = m.group(1)
    assert "'Enter'" in kb and "' '" in kb
    assert "'ArrowDown'" in kb and "'ArrowUp'" in kb
    assert "'Escape'" in kb
    assert "e.stopPropagation();" in kb, (
        "Escape here must not also bubble into the modal's own focus-trap "
        "Escape handler and close the whole Settings modal"
    )
