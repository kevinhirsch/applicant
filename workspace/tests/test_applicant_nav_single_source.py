"""Pass 2a — applicantNav.js is the SINGLE SOURCE OF TRUTH for both nav surfaces.

renderNav() builds the collapsed icon rail AND the wide sidebar tools list from
ONE ordered NAV array, so the two surfaces can no longer drift apart (the "7 nav
disagreements" this pass reconciled — different items, labels and order in the
two hand-authored index.html blocks). This suite pins that invariant against the
real ``applicantNav.js`` source, plus the load-bearing coupling to feature
gating:

  * every destination with a sidebar twin contributes the SAME id to both
    surfaces, in the same order (structurally guaranteed by the NAV array's
    shape — each item carries both its `rail` and `side` id);
  * every gated ``nav_id`` resolves to a real control — one renderNav emits or
    one still living statically in index.html. A nav_id that resolves to
    nothing fails OPEN: app.js's ``refreshApplicantFeatures`` skips a missing
    element, so the "locked" state is never applied and the control stays
    clickable;
  * the reverse guard — every destination renderNav renders for a gated
    section is present in that section's ``nav_ids`` (so the lock binds to the
    rendered control).

Source-text (regex) assertions over the real files, per this batch's
convention (see ``test_applicant_copy_indexhtml_lens02.py``). No browser, DOM
or socket.
"""

from __future__ import annotations

import pathlib
import re

from src.applicant_features import APPLICANT_SECTIONS

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
NAV_JS = REPO_ROOT / "workspace" / "static" / "js" / "applicantNav.js"
INDEX_HTML = REPO_ROOT / "workspace" / "static" / "index.html"


def _nav_src() -> str:
    return NAV_JS.read_text(encoding="utf-8")


def _nav_items() -> list[tuple[str, str | None]]:
    """Parse the ``const NAV = [ ... ];`` array's items in document order into
    a list of ``(rail_id, side_id_or_None)`` tuples (one item per line)."""
    src = _nav_src()
    m = re.search(r"const NAV = \[(.*?)\n\];", src, re.S)
    assert m, "expected a `const NAV = [ ... ];` array literal in applicantNav.js"
    body = m.group(1)
    items: list[tuple[str, str | None]] = []
    for line in body.splitlines():
        rail_m = re.search(r"\brail:\s*'([^']+)'", line)
        if not rail_m:
            continue  # group headers, spacer, comments
        side_m = re.search(r"\bside:\s*'([^']+)'", line)  # `side: null` -> no match
        items.append((rail_m.group(1), side_m.group(1) if side_m else None))
    return items


# The reconciled destination order (Today · My Job Search {Tracker, Results,
# Activity} · Applications {Documents, Gallery} · Profile · Inbox/Daily updates ·
# Calendar · Chat · [spacer] · {Update, Settings}). Same order in both surfaces.
_EXPECTED_RAIL = [
    "rail-portal", "rail-tracker", "rail-results", "rail-activity",
    "rail-archive", "rail-applicant-gallery", "rail-memory", "rail-email",
    "rail-calendar", "rail-assistant", "rail-update", "rail-settings",
]
_EXPECTED_SIDE = [
    "tool-portal-btn", "tool-tracker-btn", "tool-results-btn", "tool-activity-btn",
    "tool-library-btn", "tool-applicant-gallery-btn", "tool-memory-btn", "tool-email-btn",
    "tool-calendar-btn", "tool-assistant-btn", "tool-settings-btn",
]


def test_nav_array_parses_to_the_reconciled_rail_order():
    rails = [rail for rail, _ in _nav_items()]
    assert rails == _EXPECTED_RAIL


def test_rail_and_sidebar_destination_sets_match_in_order():
    """The single-source invariant: the destinations with a sidebar twin feed
    both surfaces the same ids in the same order. Rail-only items (Update) are
    exempt from the sidebar set."""
    items = _nav_items()
    dual = [(rail, side) for rail, side in items if side is not None]
    rail_seq = [rail for rail, _ in dual]
    side_seq = [side for _, side in dual]

    # ids are unique within each surface (no dupes)
    assert len(set(rail_seq)) == len(rail_seq)
    assert len(set(side_seq)) == len(side_seq)
    # same number of paired destinations, and each is the reconciled twin
    assert side_seq == _EXPECTED_SIDE
    assert rail_seq == [r for r in _EXPECTED_RAIL if r != "rail-update"]

    # Update is the one rail-only destination (no sidebar door in 2a).
    rail_only = [rail for rail, side in items if side is None]
    assert rail_only == ["rail-update"]


# multi_campaign_switcher was never built; its nav_ids are placeholders that
# resolve to nothing on purpose (and the section stays dormant/locked), so they
# are exempt from the "must resolve" check below (and must NOT be emitted).
_KNOWN_ABSENT = {"rail-campaigns", "tool-campaigns-btn", "rail-today"}


def test_no_dead_ids_are_emitted_by_render_nav():
    src = _nav_src()
    for dead in _KNOWN_ABSENT:
        assert f"'{dead}'" not in src, f"renderNav must not emit the dead id {dead!r}"


def test_every_gated_nav_id_resolves_to_a_real_control():
    """A gated section's nav_id must resolve to an element renderNav emits or
    that still lives statically in index.html — otherwise the lock silently
    fails OPEN."""
    nav_src = _nav_src()
    html = INDEX_HTML.read_text(encoding="utf-8")
    for section in APPLICANT_SECTIONS:
        if section.get("present_but_disabled"):
            continue
        for nav_id in section["nav_ids"]:
            if nav_id in _KNOWN_ABSENT:
                continue
            resolved = (f"'{nav_id}'" in nav_src) or (f'id="{nav_id}"' in html)
            assert resolved, (
                f"gated nav_id {nav_id!r} (section {section['key']!r}) is neither "
                f"emitted by renderNav nor present in index.html — it would fail OPEN"
            )


def test_render_nav_gated_destinations_are_locked_by_feature_nav_ids():
    """Reverse guard: every destination renderNav renders for a gated section
    must be present in that section's nav_ids, so the feature-lock binds to the
    rendered control (not a stale id)."""
    items = _nav_items()
    emitted = set()
    for rail, side in items:
        emitted.add(rail)
        if side:
            emitted.add(side)

    sections = {sec["key"]: sec for sec in APPLICANT_SECTIONS}
    # section key -> the ids renderNav actually renders for that gated surface.
    rendered_gated = {
        "documents": {"rail-archive", "tool-library-btn"},
        "gallery": {"rail-applicant-gallery", "tool-applicant-gallery-btn"},
        "memory": {"rail-memory", "tool-memory-btn"},
        "email": {"rail-email", "tool-email-btn"},
        "chat": {"rail-assistant", "tool-assistant-btn"},
        "results": {"rail-results", "tool-results-btn"},
        "update": {"rail-update"},
    }
    for key, ids in rendered_gated.items():
        nav_ids = set(sections[key]["nav_ids"])
        for rid in ids:
            assert rid in emitted, f"expected renderNav to emit {rid!r} for section {key!r}"
            assert rid in nav_ids, (
                f"{rid!r} is rendered for the gated {key!r} section but missing "
                f"from its nav_ids — it would fail OPEN"
            )


# ── Denylist hygiene (per the standing white-label instruction) ─────────────
#: the four upstream-fork codenames, split so the contiguous string never
#: appears in this file's own source (would trip the repo-wide denylist grep).
_DENYLIST_CODENAME_HALVES = (
    ("fire", "house"),
    ("or", "well"),
    ("odys", "seus"),
    ("smo", "key"),
)


def test_new_test_file_is_denylist_clean():
    text = pathlib.Path(__file__).read_text(encoding="utf-8").lower()
    for first, second in _DENYLIST_CODENAME_HALVES:
        assert (first + second) not in text
