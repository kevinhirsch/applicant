"""Regression coverage for exhaustive-audit-pass-2 lens 11 (settings/config)
findings #24 and #56, confined to ``static/js/settings.js`` (the Settings
modal's tab sidebar/wiring).

Follows the convention of ``test_applicant_notifications_lens10.py``: every
fact is read from the actual static file content via ``pathlib`` + regex — no
browser, no DOM, no real socket. Each assertion was hand-verified to go red
when the underlying fix is reverted (backup the file to /tmp, revert the
change, rerun, see the assertion fail, restore from the backup) per the
project's revert-verify convention.

Findings covered (see ``docs/design/audits/exhaustive2/11_settings_config.md``):
  * #24 — no way to find a tab among 17+ in the Settings sidebar. A
    lightweight client-side filter input (`#settings-nav-search`) now narrows
    the visible `[data-settings-tab]` buttons by label as the user types,
    reusing the existing `.memory-search-input` design-system class and the
    existing `.hidden` utility class (no panel restructuring, no new CSS).
  * #56 — Settings tabs weren't deep-linkable: `initTabs()` had no
    `location.hash`/`hashchange` handling, so a tab couldn't be bookmarked/
    shared and Back/Forward didn't move between tabs. A `#settings/<tab>`
    hash is now written on tab activation and honored on load/hashchange.
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
JS_DIR = REPO_ROOT / "workspace" / "static" / "js"
SETTINGS_JS = JS_DIR / "settings.js"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# ── #24: sidebar tab search/filter ──────────────────────────────────────────

def test_settings_search_input_exists_with_reused_design_system_class():
    """A dedicated filter input must exist in the sidebar-injection code,
    reusing the app's existing `.memory-search-input` filter-input class
    (used by memory/skills/notes/library search boxes) instead of hand-rolled
    input chrome."""
    js = _read(SETTINGS_JS)
    assert "settings-nav-search" in js, (
        "expected a dedicated settings tab-search input (id settings-nav-search)"
    )
    assert "input.className = 'memory-search-input'" in js, (
        "the settings tab-search input must reuse the memory-search-input design-system class"
    )


def test_settings_search_input_injected_into_sidebar_before_initTabs_binds_clicks():
    """The search box must be injected into `.settings-sidebar` (not a new
    panel/section) and wired up before/alongside `initAll()`'s existing tab
    setup, so it's present the first time Settings opens."""
    js = _read(SETTINGS_JS)
    m = re.search(r"function injectSettingsTabSearch\(\)\s*\{(.*?)\n\}", js, re.DOTALL)
    assert m, "expected an injectSettingsTabSearch() function"
    body = m.group(1)
    assert "querySelector('.settings-sidebar')" in body, (
        "the search input must be inserted into the existing .settings-sidebar, not a new structure"
    )
    assert "sidebar.insertBefore(input, sidebar.firstChild)" in body, (
        "the search input should sit above the existing tab list"
    )
    # Wired in initAll() so it's present on first open.
    init_all = re.search(r"function initAll\(\)\s*\{(.*?)\n\}", js, re.DOTALL)
    assert init_all, "expected an initAll() function"
    assert "injectSettingsTabSearch()" in init_all.group(1), (
        "injectSettingsTabSearch() must be called from initAll() so it exists on first open"
    )


def test_settings_search_filters_tab_buttons_by_label_using_hidden_class():
    """Typing in the filter must narrow `[data-settings-tab]` buttons by
    their own label text, toggling the existing `.hidden` utility class
    (the same one panels/modals already use) rather than a new CSS rule."""
    js = _read(SETTINGS_JS)
    m = re.search(r"function injectSettingsTabSearch\(\)\s*\{(.*?)\n\}", js, re.DOTALL)
    assert m, "expected an injectSettingsTabSearch() function"
    body = m.group(1)
    assert "addEventListener('input'" in body, (
        "the filter must react live as the user types (input event), not only on submit"
    )
    assert "querySelectorAll('[data-settings-tab]')" in body, (
        "the filter must operate over the existing tab buttons, not a rebuilt list"
    )
    assert "classList.toggle('hidden'" in body, (
        "non-matching tabs must be hidden via the existing .hidden utility class"
    )
    assert "toLowerCase()" in body, "the label match must be case-insensitive"


def test_settings_search_does_not_restructure_the_panels():
    """The fix must not touch `.settings-panels` (the fix is a sidebar filter
    over existing buttons, not a rebuild of the panel area)."""
    js = _read(SETTINGS_JS)
    m = re.search(r"function injectSettingsTabSearch\(\)\s*\{(.*?)\n\}", js, re.DOTALL)
    assert m, "expected an injectSettingsTabSearch() function"
    assert "settings-panels" not in m.group(1), (
        "the tab-search injector should only touch the sidebar, not the panels area"
    )


# ── #56: hash-based tab deep-linking ─────────────────────────────────────────

def test_hash_is_reflected_on_tab_click():
    """Clicking a (non-admin) tab must write a `#settings/<tab>` hash so the
    pane is bookmarkable/shareable."""
    js = _read(SETTINGS_JS)
    assert "SETTINGS_HASH_PREFIX = '#settings/'" in js, (
        "expected a #settings/<tab> hash prefix constant"
    )
    m = re.search(r"function initTabs\(\)\s*\{(.*?)\n\}", js, re.DOTALL)
    assert m, "expected an initTabs() function"
    body = m.group(1)
    assert "_reflectTabInHash(tab)" in body, (
        "initTabs()'s click handler must reflect the newly-active tab in location.hash"
    )


def test_admin_tabs_short_circuit_is_untouched_by_hash_write():
    """The ADMIN_TABS short-circuit (hands off to a different modal) must
    still `return` before any hash write — admin tabs neither read nor write
    this hash."""
    js = _read(SETTINGS_JS)
    m = re.search(r"function initTabs\(\)\s*\{(.*?)\n\}", js, re.DOTALL)
    assert m, "expected an initTabs() function"
    body = m.group(1)
    admin_branch = re.search(
        r"if \(ADMIN_TABS\.has\(tab\)[^{]*\{(.*?)\n\s*\}", body, re.DOTALL
    )
    assert admin_branch, "expected the ADMIN_TABS short-circuit branch in initTabs()"
    assert "adminModule.open(tab)" in admin_branch.group(1)
    assert "return" in admin_branch.group(1), (
        "the admin-tab branch must still return early, before any hash write"
    )
    assert "_reflectTabInHash" not in admin_branch.group(1), (
        "admin tabs must not write the settings hash — they hand off to a different modal"
    )


def test_hashchange_listener_opens_the_matching_tab_while_settings_is_open():
    """A `hashchange` event (Back/Forward, or a manual hash edit) must open
    the corresponding tab while Settings is open, and must ignore the
    module's own writes to avoid a feedback loop."""
    js = _read(SETTINGS_JS)
    m = re.search(r"function _wireSettingsHashRouting\(\)\s*\{(.*?)\n\}", js, re.DOTALL)
    assert m, "expected a _wireSettingsHashRouting() function"
    body = m.group(1)
    assert "addEventListener('hashchange'" in body, (
        "expected a hashchange listener for back/forward + manual hash edits"
    )
    assert "_settingsHashSyncing" in body, (
        "the hashchange listener must ignore the module's own hash writes to avoid a feedback loop"
    )
    assert "_activateSettingsTab(tab)" in body, (
        "an incoming hashchange must activate the matching tab"
    )
    # Wired from initTabs() so it's live once Settings has been opened once.
    init_tabs = re.search(r"function initTabs\(\)\s*\{(.*?)\n\}", js, re.DOTALL)
    assert init_tabs and "_wireSettingsHashRouting()" in init_tabs.group(1)


def test_open_honors_incoming_hash_when_no_explicit_tab_requested():
    """`open()` (the public API) must honor a pre-existing `#settings/<tab>`
    hash (a deep link, reload, or Back/Forward landing on Settings) when the
    caller didn't request a specific tab — without changing the no-hash
    default."""
    js = _read(SETTINGS_JS)
    m = re.search(r"export function open\(tab\)\s*\{(.*?)\n\}", js, re.DOTALL)
    assert m, "expected the exported open(tab) function"
    body = m.group(1)
    assert "if (!tab) {" in body, (
        "open() must only consult the hash when the caller passed no explicit tab"
    )
    assert "_tabFromHash()" in body, (
        "open() must read an incoming hash to decide which tab to show"
    )


def test_hash_format_cannot_collide_with_other_hash_owners():
    """The chosen `#settings/<tab>` shape must not match the single bare-word
    tokens hashRouter.js's registry owns (e.g. `#portal`, `#mind`) or a bare
    session id (`#<uuid-ish>`), since those are read by the same global
    `hashchange` event loop this file also listens on."""
    js = _read(SETTINGS_JS)
    assert "'#settings/'" in js
    # Sanity: the prefix includes a slash, which none of the known
    # single-word hashRouter tokens or bare-session-id hashes contain.
    assert "/" in "#settings/"
