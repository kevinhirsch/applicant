"""White-label regression guards for the front-door shell (static/index.html
and a couple of static/js modules).

A live UI audit found vendored-workspace bleed in the white-labeled front door:
sidebar list-items for tools that are NOT Applicant surfaces (Calendar,
Cookbook, Deep Research, a duplicate image Gallery, Notes, Tasks, Theme), an
off-product roleplay persona system (presets.js / the Character modal tab), an
Odysseus "king of Ithaca" persona string, and vendored AI-media Settings cards
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
_PRESETS = _REPO / "static" / "js" / "presets.js"
_CALENDAR = _REPO / "static" / "js" / "calendar.js"

# The 7 vendored sidebar tools that must NOT render as visible Applicant
# surfaces. (The real Applicant surfaces — gallery/assistant/compare/debug/
# email/library/memory — are intentionally absent from this list.)
HIDDEN_SIDEBAR_IDS = [
    "tool-calendar-btn",
    "tool-cookbook-btn",
    "tool-research-btn",
    "tool-gallery-btn",
    "tool-notes-btn",
    "tool-tasks-btn",
    "tool-theme-btn",
]

# Applicant surfaces that MUST stay visible — a guard against over-hiding.
KEEP_SIDEBAR_IDS = [
    "tool-applicant-gallery-btn",
    "tool-assistant-btn",
    "tool-compare-btn",
    "tool-debug-btn",
    "tool-email-btn",
    "tool-library-btn",
    "tool-memory-btn",
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


def test_vendored_sidebar_tools_are_hidden():
    items = _sidebar_items()
    for tool_id in HIDDEN_SIDEBAR_IDS:
        assert tool_id in items, f"{tool_id} not found in sidebar — id may have drifted"
        assert items[tool_id]["hidden"], (
            f"{tool_id} renders as a VISIBLE sidebar item — it must carry "
            f"display:none (vendored-tool bleed in the white-label front door)"
        )


def test_applicant_sidebar_surfaces_stay_visible():
    items = _sidebar_items()
    for tool_id in KEEP_SIDEBAR_IDS:
        assert tool_id in items, f"{tool_id} not found in sidebar — id may have drifted"
        assert not items[tool_id]["hidden"], (
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


def test_no_ithaca_or_odysseus_persona_leak():
    for path in (_PRESETS, _CALENDAR):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"ithaca", text, re.IGNORECASE), (
            f"{path.name} still contains 'Ithaca' — off-product roleplay-persona leak"
        )
        assert not re.search(r"king of ithaca", text, re.IGNORECASE), (
            f"{path.name} still contains the 'king of Ithaca' persona string"
        )
