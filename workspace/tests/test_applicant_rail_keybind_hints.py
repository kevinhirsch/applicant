"""Regression coverage for lens 12 #17: "only #rail-search-btn shows its
shortcut ('(Ctrl+K)') in its title; every other rail button (Portal, Update,
Results, Tracker, Assistant, Archive, Profile, etc.) has a title with no
bound-shortcut suffix, even when a keybinding exists."

Fixed entirely inside ``static/js/keyboard-shortcuts.js`` — the module that
already owns the live, user-customizable keybind map
(``window._applicantKeybinds``) and the click-wiring for the rail buttons
whose actions have a keybinding. At runtime it now:

  - Maps each keybind-driven rail button id to its keybind-map action
    (``_RAIL_KEYBIND_MAP``) — new/delete session, search, and every
    "open a tool" rail icon that has a corresponding ``open_*`` action.
  - Formats a combo the same "(Ctrl+K)" way ``#rail-search-btn``'s own
    hard-coded title already does (``_formatKeybindHint``), so the visual
    convention stays identical whether the hint was authored by hand (search)
    or appended at runtime (every other rail button).
  - Appends that hint to each button's ``title``/``aria-label`` at runtime
    (``_applyRailKeybindHints``), caching the hint-free base text in a
    ``dataset`` attribute the first time it sees a button and skipping any
    base title that already ends in a "(...)" suffix — so re-running after a
    Settings rebind replaces rather than stacks hints, and the hand-authored
    ``#rail-search-btn`` title is never double-suffixed.
  - Is invoked right after the default keybinds are assigned (covers the
    common case before the saved-settings fetch resolves) and again once that
    fetch resolves (covers a user's saved rebind, including unbinding down to
    empty).

Nothing else was touched. This suite is confined to
``static/js/keyboard-shortcuts.js`` and reads the real file content — no
browser, no DOM, no real socket — per this batch's source-assertion
convention (see e.g. ``test_applicant_round1_remainder_shell.py``).

Every assertion here was hand-verified to go RED when the corresponding piece
of logic is reverted (temporarily backed up out-of-tree, never via
``git stash``) and GREEN again once restored.
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
KEYBOARD_SHORTCUTS_JS = REPO_ROOT / "static" / "js" / "keyboard-shortcuts.js"


def _read() -> str:
    return KEYBOARD_SHORTCUTS_JS.read_text(encoding="utf-8")


# Rail ids whose click already delegates to one of these keybind actions
# (see keyboard-shortcuts.js's own `_toolBtns` / app.js's `_railToolMap`).
# Every one of these must gain a live keybind hint at runtime.
EXPECTED_RAIL_ACTIONS = {
    "rail-search-btn": "search",
    "rail-new-session": "new_session",
    "rail-delete-session": "delete_session",
    "rail-calendar": "open_calendar",
    "rail-compare": "open_compare",
    "rail-cookbook": "open_cookbook",
    "rail-research": "open_research",
    "rail-gallery": "open_gallery",
    "rail-archive": "open_library",
    "rail-memory": "open_memory",
    "rail-notes": "open_notes",
    "rail-tasks": "open_tasks",
    "rail-theme": "open_theme",
}


def _extract_object_body(src: str, var_name: str) -> str:
    m = re.search(rf"\b{re.escape(var_name)}\s*=\s*\{{", src)
    assert m, f"expected an object literal assigned to {var_name} in keyboard-shortcuts.js"
    start = m.end()
    depth = 1
    i = start
    while depth > 0:
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
        i += 1
    return src[start : i - 1]


def test_rail_keybind_map_covers_every_keybind_driven_rail_button():
    """`_RAIL_KEYBIND_MAP` must pair each rail button id with the exact
    keybind action its click already triggers, so the right combo is looked
    up for its hint."""
    body = _extract_object_body(_read(), "_RAIL_KEYBIND_MAP")
    for rail_id, action in EXPECTED_RAIL_ACTIONS.items():
        pattern = rf"['\"]{re.escape(rail_id)}['\"]\s*:\s*['\"]{re.escape(action)}['\"]"
        assert re.search(pattern, body), (
            f"_RAIL_KEYBIND_MAP should map {rail_id!r} -> {action!r} "
            f"(the action its click already delegates to)"
        )


def test_rail_keybind_map_has_no_stray_entries():
    """Sanity check the map isn't secretly wider/narrower than the buttons
    this fix targets (would silently mask a missing or bogus mapping)."""
    body = _extract_object_body(_read(), "_RAIL_KEYBIND_MAP")
    pairs = re.findall(r"['\"]([\w-]+)['\"]\s*:\s*['\"]([\w-]+)['\"]", body)
    assert dict(pairs) == EXPECTED_RAIL_ACTIONS


def test_format_keybind_hint_uses_the_existing_parenthesis_style():
    """The runtime-appended hint must render in the same "(Ctrl+K)" style
    #rail-search-btn's own hard-coded title already uses, not some other
    format."""
    src = _read()
    m = re.search(r"function _formatKeybindHint\([^)]*\)\s*\{(.*?)\n\}", src, re.S)
    assert m, "expected a _formatKeybindHint(combo) function"
    body = m.group(1)
    assert "'Ctrl'" in body and "'Alt'" in body and "'Shift'" in body, (
        "expected the modifier keys to render capitalized, matching the "
        "existing '(Ctrl+K)' convention"
    )
    assert "'Esc'" in body, "expected 'escape' to render as 'Esc'"
    # Must wrap the joined parts in literal parens, e.g. `(${parts.join('+')})`.
    assert re.search(r"\(\$\{.*join\(['\"]\+['\"]\)\}\)", body), (
        "expected the combo to be wrapped in literal parens like '(Ctrl+K)'"
    )


def test_apply_rail_keybind_hints_skips_titles_that_already_have_a_suffix():
    """Must not double-suffix #rail-search-btn's own hand-authored
    '(Ctrl+K)' title, and must not stack a stale hint on top of a fresh one
    across re-runs (e.g. after a Settings rebind)."""
    src = _read()
    m = re.search(r"function _applyRailKeybindHints\(\)\s*\{(.*?)\n\}", src, re.S)
    assert m, "expected an _applyRailKeybindHints() function"
    body = m.group(1)
    assert "dataset.baseTitle" in body, (
        "expected the hint-free base title to be cached (e.g. on a dataset "
        "attribute) so re-runs replace rather than stack the hint"
    )
    assert re.search(r"\\\(\[\^\(\)\]\*\\\)", body), (
        "expected a guard that detects an existing trailing '(...)' suffix "
        "(rail-search-btn's own hard-coded hint) and leaves it alone"
    )


def test_apply_rail_keybind_hints_sets_title_and_aria_label():
    src = _read()
    m = re.search(r"function _applyRailKeybindHints\(\)\s*\{(.*?)\n\}", src, re.S)
    assert m
    body = m.group(1)
    assert "setAttribute('title'" in body
    assert "setAttribute('aria-label'" in body
    # Looked up from the live, user-customizable map (so a Settings rebind
    # is reflected), not the static defaults.
    assert "window._applicantKeybinds" in body


def test_apply_rail_keybind_hints_is_invoked_after_default_and_after_saved_fetch():
    """Must run once right after the default keybinds are assigned (covers
    page-load before the settings fetch resolves) and again once the saved
    keybinds are merged in (covers a user's own rebind)."""
    src = _read()

    default_assign = re.search(
        r"window\._applicantKeybinds\s*=\s*\{\s*\.\.\._defaultKeybinds\s*\};"
        r"\s*\n\s*_applyRailKeybindHints\(\);",
        src,
    )
    assert default_assign, (
        "expected _applyRailKeybindHints() to be called immediately after "
        "`window._applicantKeybinds = { ..._defaultKeybinds };`"
    )

    fetch_block = re.search(
        r"fetch\('/api/auth/settings'.*?\.finally\(\(\)\s*=>\s*_applyRailKeybindHints\(\)\);",
        src,
        re.S,
    )
    assert fetch_block, (
        "expected the /api/auth/settings fetch chain to re-run "
        "_applyRailKeybindHints() once it settles (success or failure), so "
        "a saved rebind updates the rail tooltips too"
    )
