"""Regression coverage for road-to-market story P0-5 — "Empty states that sell."

The shared empty-state component (``applicantCore.js`` ``emptyHTML``) now
implements the agreed design — icon + sentence + one real CTA — and the
sections that still had CTA-less or bespoke empty/gated panes were swept so
every empty section tells the user what will live there and routes them
somewhere real:

- ``applicantCore.js``: ``emptyHTML`` gained an icon slot (ui.js
  ``emptyStateIcon``, ``currentColor`` so it follows light/dark themes; the
  behavioral composition tests live in ``tests/js/applicantEmptyStates.test.js``).
- ``applicantTracker.js``: the two "Nothing to track yet" empty states gained a
  "See what I'm working on" CTA routing to the Activity page (same target as
  Results' existing empty CTA); the gated state gained the one-tap "Finish
  setup" resume Today already had; offline uses the calm neutral icon.
- ``applicantActivity.js``: the bespoke offline ``<div>`` was rewritten onto
  the shared kit; the bespoke gated ``<div>`` became ``gatedHTML`` with a
  "Finish setup" CTA; the "Warming up" empty state gained a "See today's plan"
  CTA routing to Today.
- ``applicantResults.js``: the gated state gained the "Finish setup" CTA;
  offline uses the neutral icon.
- ``applicantToday.js`` / ``applicantCompare.js``: their offline / no-data
  states pass the neutral icon kind (calm, not celebratory).

Follows the convention of ``test_applicant_backlog_warmempty.py``: every fact
is read from the actual static file content via ``pathlib`` — no browser, no
DOM, no real socket (these modules do top-level launcher wiring on import, so
they are not importable under bare node without a DOM shim).
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
JS_DIR = REPO_ROOT / "workspace" / "static" / "js"

CORE_JS = JS_DIR / "applicantCore.js"
TRACKER_JS = JS_DIR / "applicantTracker.js"
ACTIVITY_JS = JS_DIR / "applicantActivity.js"
RESULTS_JS = JS_DIR / "applicantResults.js"
TODAY_JS = JS_DIR / "applicantToday.js"
COMPARE_JS = JS_DIR / "applicantCompare.js"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _fn(src: str, name: str) -> str:
    """Extract a top-level `function name(...) { ... }` body (same convention
    as test_applicant_round2_wave1_corekit.py's `_top_level_fn`)."""
    m = re.search(rf"function {re.escape(name)}\([^)]*\)\s*\{{(.*?)\n\}}", src, re.S)
    assert m, f"expected a top-level function {name}(...)"
    return m.group(1)


# ── applicantCore.js — the shared component is icon + sentence + CTA ─────────

def test_shared_empty_component_has_icon_slot_reusing_ui_kit():
    src = _read(CORE_JS)
    body = _fn(src, "emptyHTML")
    # Reuses the app's existing empty-state icon (lift-and-shift), never a
    # bespoke inline SVG of its own.
    assert "uiModule.emptyStateIcon" in body
    # Decoration only: hidden from AT, and omittable via a falsy icon kind.
    assert 'aria-hidden="true"' in body
    assert re.search(r"icon\s*=\s*'smiley'", src), "default icon kind is the smiley"
    # Theme correctness: copy colors come from theme variables.
    assert "var(--fg-muted)" in body and "var(--fg)" in body


# ── applicantTracker.js — empty + gated states route somewhere real ──────────

def test_tracker_empty_states_carry_the_activity_cta():
    src = _read(TRACKER_JS)
    assert "applicant-tracker-empty-activity" in src
    assert "See what I’m working on" in src
    # Both the fetch-level empty state and the board's own inline empty case
    # pass the CTA and wire it.
    assert src.count("_EMPTY_ACTIVITY_CTA_HTML") >= 3  # const + two call sites
    # The CTA opens Activity via its exported launcher (this modal is not
    # hash-router-registered, so a bare setHash could dead-end — Greptile on
    # #747); the hash write remains as fallback.
    assert "window.applicantActivityModule.openApplicantActivity()" in src
    assert "setHash('activity')" in src
    empty = _fn(src, "_renderEmpty")
    assert "_EMPTY_ACTIVITY_CTA_HTML" in empty and "_wireEmptyActivityCTA" in empty


def test_tracker_gated_state_offers_finish_setup_not_a_dead_end():
    src = _read(TRACKER_JS)
    gated = _fn(src, "_renderGated")
    assert "applicant-tracker-gated-setup" in gated
    assert "Finish setup" in gated
    assert "window.launchApplicantSetup" in gated


def test_tracker_offline_uses_the_calm_neutral_icon():
    src = _read(TRACKER_JS)
    offline = _fn(src, "_renderOffline")
    assert "'neutral'" in offline


# ── applicantActivity.js — bespoke divs onto the kit, CTAs wired ──────────────

def test_activity_offline_rides_the_shared_kit_not_a_bespoke_div():
    src = _read(ACTIVITY_JS)
    offline = _fn(src, "_renderOffline")
    assert "emptyHTML(" in offline
    assert "'neutral'" in offline
    # The pinned first-person copy survives the re-plumbing.
    assert "My activity will appear here once I'm connected and running." in src


def test_activity_gated_state_offers_finish_setup():
    src = _read(ACTIVITY_JS)
    gated = _fn(src, "_renderGated")
    assert "gatedHTML(" in gated
    assert "applicant-activity-gated-setup" in gated
    assert "window.launchApplicantSetup" in gated


def test_activity_empty_state_routes_to_today():
    src = _read(ACTIVITY_JS)
    empty = _fn(src, "_renderEmpty")
    assert "applicant-activity-empty-today" in empty
    assert "See today’s plan" in empty
    assert "setHash('today')" in empty


# ── applicantResults.js — gated CTA + neutral offline ────────────────────────

def test_results_gated_state_offers_finish_setup():
    src = _read(RESULTS_JS)
    gated = _fn(src, "_renderGated")
    assert "applicant-results-gated-setup" in gated
    assert "window.launchApplicantSetup" in gated
    # The plain-language fallback message pinned by the lens02 copy test stays.
    assert "Finish setup and connect a model — your results will start appearing here." in src


def test_results_offline_uses_the_calm_neutral_icon():
    src = _read(RESULTS_JS)
    offline = _fn(src, "_renderOffline")
    assert "'neutral'" in offline


# ── Today / Compare — soft states pick the neutral icon ──────────────────────

def test_today_offline_and_compare_no_data_pick_neutral():
    today = _fn(_read(TODAY_JS), "_renderOffline")
    assert "'neutral'" in today
    compare = _read(COMPARE_JS)
    assert re.search(r"No comparison came back'[\s\S]{0,200}'neutral'", compare)
