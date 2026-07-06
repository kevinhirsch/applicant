"""White-label regression guards for the front-door shell (static/index.html
and a couple of static/js modules).

A live UI audit found vendored-workspace bleed in the white-labeled front door:
sidebar list-items for tools that are NOT Applicant surfaces (Calendar,
Cookbook, Deep Research, a duplicate image Gallery, Notes, Tasks, Theme), an
off-product roleplay persona system (presets.js / the Character modal tab), an
upstream "king of Ithaca" persona string, and vendored AI-media Settings cards
(Vision, Teacher Model, Image Generation, Text-to-Speech) that aren't part of
the job-application product.

These assertions pin the fixes so the bleed can't silently come back. They are
dependency-light (stdlib html.parser + string checks, no network, no node) so
they run in the hermetic front-door lane.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_INDEX = _REPO / "static" / "index.html"
_APP_JS = _REPO / "static" / "app.js"
_PRESETS = _REPO / "static" / "js" / "presets.js"
_CALENDAR = _REPO / "static" / "js" / "calendar.js"
# Pass 2a: the Applicant surfaces' sidebar list-items moved out of index.html
# into applicantNav.js's single-source NAV array (see
# ``test_applicant_nav_single_source.py``). The vendored (hidden) tools stay
# static here, unaffected.
_NAV_JS = _REPO / "static" / "js" / "applicantNav.js"

# The UI_VIS_MAP keys for the 7 vendored sidebar tools. Inline display:none in
# index.html (HIDDEN_SIDEBAR_IDS) is NOT enough on its own: app.js
# applyUIVis(loadUIVis()) iterates UI_VIS_MAP and force-sets el.style.display
# for every key it contains — to '' (visible) unless the key is in
# UI_VIS_DEFAULT_OFF and absent from localStorage — re-revealing these tools at
# runtime. So the runtime guard below asserts each vendored key is either ABSENT
# from UI_VIS_MAP (preferred — inline display:none then holds unconditionally) or
# present in UI_VIS_DEFAULT_OFF. This is the assertion that would FAIL on the
# pre-fix main (where the keys sit in UI_VIS_MAP and not in DEFAULT_OFF).
VENDORED_UI_VIS_KEYS = [
    "tool-calendar",
    "tool-cookbook",
    "tool-research",
    "tool-gallery",
    "tool-notes",
    "tool-tasks",
    "tool-theme",
]

# The 6 vendored sidebar tools that must NOT render as visible Applicant
# surfaces. (The real Applicant surfaces — gallery/assistant/compare/debug/
# email/library/memory/... — are intentionally absent from this list.)
# tool-calendar-btn used to live here too, but Calendar is now a KEPT
# (visible) Applicant surface (Pass 2a design decision #2) — moved below.
HIDDEN_SIDEBAR_IDS = [
    "tool-cookbook-btn",
    "tool-research-btn",
    "tool-gallery-btn",
    "tool-notes-btn",
    "tool-tasks-btn",
    "tool-theme-btn",
]

# Applicant surfaces that MUST stay visible — a guard against over-hiding.
# Pass 2a: all of these are now emitted by applicantNav.js's NAV array
# (renderNav's `_sidebarItem()`) rather than being static index.html divs —
# see `_nav_side_ids()` below, which `test_applicant_sidebar_surfaces_stay_
# visible` consults for any id no longer found as static markup.
KEEP_SIDEBAR_IDS = [
    "tool-portal-btn",
    "tool-tracker-btn",
    "tool-results-btn",
    "tool-activity-btn",
    "tool-library-btn",
    "tool-applicant-gallery-btn",
    "tool-memory-btn",
    "tool-email-btn",
    "tool-calendar-btn",
    "tool-assistant-btn",
    "tool-compare-btn",
    "tool-debug-btn",
    "tool-trust-btn",
]

# Vendored AI-media / agent-training Settings cards. Each toggle input must sit
# inside a display:none ancestor (the card is hidden, the input kept so the
# vendored settings.js wiring doesn't throw on missing nodes).
HIDDEN_SETTINGS_TOGGLE_IDS = [
    "set-imgEnabledToggle",
    "set-ttsEnabledToggle",
    "set-visionEnabledToggle",
    "set-teacherEnabledToggle",
]


def _style_is_hidden(style: str) -> bool:
    return "display:none" in (style or "").replace(" ", "").lower()


# HTML void elements never get an end tag, so they must not push onto the
# open-element stack (otherwise an earlier hidden <input>/<br>/... would leak
# its hidden flag onto everything that follows).
_VOID = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}


class _SidebarParser(HTMLParser):
    """Collect the sidebar list-items and their grow-span labels.

    Records, per `<div class="list-item" id="...">`, whether it (or an open
    ancestor) is display:none, plus the text inside its `<span class="grow">`.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._stack: list[dict] = []  # open elements: {hidden: bool}
        # id -> {"hidden": bool, "label": str}
        self.items: dict[str, dict] = {}
        self._cur_item_id: str | None = None
        self._cur_item_depth: int | None = None
        self._in_grow = False
        self._grow_depth: int | None = None

    def _note_item(self, attr, hidden, depth):
        classes = attr.get("class", "").split()
        if "list-item" in classes and attr.get("id"):
            self._cur_item_id = attr["id"]
            self._cur_item_depth = depth
            self.items[attr["id"]] = {"hidden": hidden, "label": ""}
        if self._cur_item_id and "grow" in classes:
            self._in_grow = True
            self._grow_depth = depth

    def handle_starttag(self, tag, attrs):
        attr = {k: (v or "") for k, v in attrs}
        ancestor_hidden = any(e["hidden"] for e in self._stack)
        hidden = ancestor_hidden or _style_is_hidden(attr.get("style", ""))
        if tag in _VOID:
            self._note_item(attr, hidden, len(self._stack))
            return
        self._stack.append({"hidden": hidden})
        self._note_item(attr, hidden, len(self._stack))

    def handle_startendtag(self, tag, attrs):
        # Self-closing tag (e.g. SVG <rect .../>) — no nesting effect.
        attr = {k: (v or "") for k, v in attrs}
        ancestor_hidden = any(e["hidden"] for e in self._stack)
        hidden = ancestor_hidden or _style_is_hidden(attr.get("style", ""))
        self._note_item(attr, hidden, len(self._stack))

    def handle_endtag(self, tag):
        if tag in _VOID:
            return
        depth = len(self._stack)
        if self._in_grow and self._grow_depth is not None and depth <= self._grow_depth:
            self._in_grow = False
            self._grow_depth = None
        if self._cur_item_depth is not None and depth <= self._cur_item_depth:
            self._cur_item_id = None
            self._cur_item_depth = None
        if self._stack:
            self._stack.pop()

    def handle_data(self, data):
        if self._in_grow and self._cur_item_id:
            self.items[self._cur_item_id]["label"] += data


class _ToggleAncestorParser(HTMLParser):
    """Record, for each input id of interest, whether it is rendered inside a
    display:none ancestor element."""

    def __init__(self, target_ids: list[str]) -> None:
        super().__init__(convert_charrefs=True)
        self._stack: list[bool] = []  # hidden flag per open element
        self._targets = set(target_ids)
        self.hidden_for: dict[str, bool] = {}

    def handle_starttag(self, tag, attrs):
        attr = {k: (v or "") for k, v in attrs}
        ancestor_hidden = any(self._stack)
        hidden = ancestor_hidden or _style_is_hidden(attr.get("style", ""))
        # Void elements (incl. <input>) never get an endtag — record without
        # pushing, so an earlier hidden void element can't leak its flag.
        if attr.get("id") in self._targets:
            self.hidden_for[attr["id"]] = hidden
        if tag not in _VOID:
            self._stack.append(hidden)

    def handle_startendtag(self, tag, attrs):
        attr = {k: (v or "") for k, v in attrs}
        ancestor_hidden = any(self._stack)
        hidden = ancestor_hidden or _style_is_hidden(attr.get("style", ""))
        if attr.get("id") in self._targets:
            self.hidden_for[attr["id"]] = hidden

    def handle_endtag(self, tag):
        if tag not in _VOID and self._stack:
            self._stack.pop()


def _sidebar_items() -> dict[str, dict]:
    p = _SidebarParser()
    p.feed(_INDEX.read_text(encoding="utf-8"))
    return p.items


def _nav_side_ids() -> set[str]:
    """Sidebar-item ids (`side: '...'`) emitted by applicantNav.js's NAV
    array. `_sidebarItem()` (verified below to have no hidden/display:none
    branch) is the ONE render path for these, so an id being present in NAV
    means it renders unconditionally -- visible -- whenever the shell mounts."""
    src = _NAV_JS.read_text(encoding="utf-8")
    m = re.search(r"const NAV = \[(.*?)\n\];", src, re.S)
    assert m, "expected a `const NAV = [ ... ];` array literal in applicantNav.js"
    return set(re.findall(r"\bside:\s*'([^']+)'", m.group(1)))


def test_vendored_sidebar_tools_are_hidden():
    items = _sidebar_items()
    for tool_id in HIDDEN_SIDEBAR_IDS:
        assert tool_id in items, f"{tool_id} not found in sidebar — id may have drifted"
        assert items[tool_id]["hidden"], (
            f"{tool_id} renders as a VISIBLE sidebar item — it must carry "
            f"display:none (vendored-tool bleed in the white-label front door)"
        )
    # And none of the vendored ids leaked into the Pass 2a single-source NAV
    # array either (the only other place a sidebar item could come from).
    nav_ids = _nav_side_ids()
    for tool_id in HIDDEN_SIDEBAR_IDS:
        assert tool_id not in nav_ids, (
            f"{tool_id} is a vendored tool but is emitted by applicantNav.js "
            f"— vendored-tool bleed into the reconciled job-search nav"
        )


def test_applicant_sidebar_surfaces_stay_visible():
    """Applicant surfaces must render visibly — either as a non-hidden,
    still-static index.html list-item, or (Pass 2a) as a `side` entry in
    applicantNav.js's NAV array. `_sidebarItem()` has no conditional
    hidden/display:none path (checked below), so being present in NAV is
    itself proof of visibility — the single source of truth these surfaces
    moved to."""
    nav_src = _NAV_JS.read_text(encoding="utf-8")
    sidebaritem_m = re.search(r"function _sidebarItem\(item\)\s*\{(.*?)\n\}", nav_src, re.S)
    assert sidebaritem_m, "expected a _sidebarItem(item) function in applicantNav.js"
    sidebaritem_body = sidebaritem_m.group(1)
    assert "display:none" not in sidebaritem_body.replace(" ", "")
    assert "hidden" not in sidebaritem_body.lower()

    static_items = _sidebar_items()
    nav_ids = _nav_side_ids()
    for tool_id in KEEP_SIDEBAR_IDS:
        if tool_id in nav_ids:
            continue  # emitted unconditionally by applicantNav.js -- visible
        assert tool_id in static_items, f"{tool_id} not found in sidebar — id may have drifted"
        assert not static_items[tool_id]["hidden"], (
            f"{tool_id} is an Applicant surface but got hidden — over-hiding regression"
        )


def test_no_duplicate_visible_sidebar_labels():
    items = _sidebar_items()
    seen: dict[str, str] = {}
    for tool_id, meta in items.items():
        if meta["hidden"]:
            continue
        label = meta["label"].strip().lower()
        if not label:
            continue
        assert label not in seen, (
            f"Two visible sidebar items share the label '{meta['label'].strip()}': "
            f"{seen[label]} and {tool_id} (duplicate-tool bleed, e.g. the vendored Gallery)"
        )
        seen[label] = tool_id


def test_vendored_settings_cards_are_hidden():
    parser = _ToggleAncestorParser(HIDDEN_SETTINGS_TOGGLE_IDS)
    parser.feed(_INDEX.read_text(encoding="utf-8"))
    for toggle_id in HIDDEN_SETTINGS_TOGGLE_IDS:
        assert toggle_id in parser.hidden_for, (
            f"{toggle_id} not found in index.html — id may have drifted"
        )
        assert parser.hidden_for[toggle_id], (
            f"the Settings card holding {toggle_id} is VISIBLE — vendored AI-media "
            f"subsystem must be hidden (display:none) in the white-label front door"
        )


def _parse_app_js_vis() -> tuple[set[str], set[str]]:
    """Return (UI_VIS_MAP keys, UI_VIS_DEFAULT_OFF members) parsed from app.js.

    Pure string/regex parse — no node, no network — so it runs in the hermetic
    front-door lane while still capturing the *runtime* behaviour of applyUIVis.
    """
    text = _APP_JS.read_text(encoding="utf-8")

    map_m = re.search(r"const\s+UI_VIS_MAP\s*=\s*\{(.*?)\}", text, re.DOTALL)
    assert map_m, "UI_VIS_MAP object not found in app.js — symbol may have drifted"
    # Keys are the quoted identifiers on the left of each `'key': 'selector'` pair.
    map_keys = set(re.findall(r"'([^']+)'\s*:", map_m.group(1)))

    off_m = re.search(
        r"const\s+UI_VIS_DEFAULT_OFF\s*=\s*new\s+Set\(\[(.*?)\]\)", text, re.DOTALL
    )
    assert off_m, "UI_VIS_DEFAULT_OFF set not found in app.js — symbol may have drifted"
    default_off = set(re.findall(r"'([^']+)'", off_m.group(1)))

    return map_keys, default_off


def test_vendored_tools_not_re_revealed_at_runtime():
    """Runtime guard: applyUIVis must not force the 7 vendored tools visible.

    Static index.html display:none alone passed while the live UI was wrong
    (PR #542) because applyUIVis overwrites inline display for every UI_VIS_MAP
    key. Each vendored key must therefore be absent from UI_VIS_MAP (so applyUIVis
    never touches it) or, failing that, present in UI_VIS_DEFAULT_OFF.
    """
    map_keys, default_off = _parse_app_js_vis()
    for key in VENDORED_UI_VIS_KEYS:
        honoured = key not in map_keys or key in default_off
        assert honoured, (
            f"UI_VIS_MAP key '{key}' is present in UI_VIS_MAP and absent from "
            f"UI_VIS_DEFAULT_OFF — applyUIVis will force-set its display to '' and "
            f"re-reveal this vendored tool at runtime despite the inline "
            f"display:none. Drop it from UI_VIS_MAP or add it to UI_VIS_DEFAULT_OFF."
        )


def test_kept_applicant_vis_keys_stay_toggleable():
    """Guard against over-hiding: the kept user-toggleable Applicant tools must
    stay in UI_VIS_MAP and out of UI_VIS_DEFAULT_OFF (visible by default)."""
    map_keys, default_off = _parse_app_js_vis()
    for key in ("tool-memory", "tool-compare", "tool-library"):
        assert key in map_keys, f"'{key}' dropped from UI_VIS_MAP — over-hiding regression"
        assert key not in default_off, (
            f"'{key}' is an Applicant surface but defaults OFF — over-hiding regression"
        )


def test_appearance_toggle_has_no_vendored_rows():
    """The Appearance 'Sidebar' visibility list must not expose data-ui-key rows
    for the vendored tools — otherwise a user could re-enable an off-product
    surface that FIX 1 hid."""
    text = _INDEX.read_text(encoding="utf-8")
    ui_keys = set(re.findall(r'data-ui-key="([^"]+)"', text))
    for key in VENDORED_UI_VIS_KEYS:
        assert key not in ui_keys, (
            f'Appearance toggle row data-ui-key="{key}" still present — remove the '
            f"vendored-tool visibility toggle from the white-label front door"
        )


def test_no_upstream_ithaca_persona_leak():
    for path in (_PRESETS, _CALENDAR):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"ithaca", text, re.IGNORECASE), (
            f"{path.name} still contains 'Ithaca' — off-product roleplay-persona leak"
        )
        assert not re.search(r"king of ithaca", text, re.IGNORECASE), (
            f"{path.name} still contains the 'king of Ithaca' persona string"
        )
