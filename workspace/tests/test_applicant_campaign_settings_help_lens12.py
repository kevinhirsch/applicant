"""Regression coverage for exhaustive2 lens 12 (help & self-explainability),
findings #12-14 — see ``docs/design/audits/exhaustive2/12_help_selfexplain.md``.

Finding #14 named ``applicantCampaignSettings.js`` the worst tooltip-coverage
offender in the whole product: "every input... ships a bare label." A prior
pass (see ``test_applicant_exhaustive2_copyvoice_today_campaignsettings_
gallery.py``) already added inline explainer copy to the "Daily target" and
"Trying new sources" fields, but left the **Name** field, the **Run mode**
control, and the **source-toggle checkboxes** (the discovery-sources list)
completely bare — confirmed still-unfixed by this task's own re-audit.

This pass is ADDITIVE ONLY (new copy/`title=` tooltips, matching the existing
inline-explainer style already used for the two fixed fields) — no DOM
restructuring, no behavior change. Every assertion below is a source-text
check, matching this surface's existing test convention (regex over the
file's own text; the render functions only produce real DOM in a browser).

  * Name field: inline explainer span next to the label + a `title=` on the
    input restating that it's just a label, not a search parameter.
  * Run mode: inline explainer span next to the label + a `title=` on the
    `<select>` spelling out what each of the three modes does.
  * Source-toggle checkboxes: each row's wrapping `<label>` gets a `title=`
    explaining what checking/unchecking a source actually does (stop/resume
    searching it; learned stats are kept either way).

Verified RED on revert / GREEN on restore: this file's source-text checks
were run against a `/tmp`-backed copy of the pre-fix
``applicantCampaignSettings.js`` (via a plain file copy, never `git stash`)
and confirmed to fail there, then re-run against the fixed file and confirmed
to pass, before landing this test.
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess

import pytest

_REPO = pathlib.Path(__file__).resolve().parent.parent  # workspace/
_JS_DIR = _REPO / "static" / "js"
_CAMPAIGN_SETTINGS_JS = _JS_DIR / "applicantCampaignSettings.js"

_HAS_NODE = shutil.which("node") is not None


@pytest.fixture(scope="module")
def node_available():
    if not _HAS_NODE:
        pytest.skip("node binary not on PATH")


def _cs_src() -> str:
    return _CAMPAIGN_SETTINGS_JS.read_text(encoding="utf-8")


def _campaign_card_fn(src: str) -> str:
    fn = re.search(r"function _campaignCard\(c\)\s*\{[\s\S]*?\n\}", src)
    assert fn, "expected _campaignCard(c)"
    return fn.group(0)


def _render_sources_fn(src: str) -> str:
    fn = re.search(r"function _renderSources\(host, campaignId, items\)\s*\{[\s\S]*?\n\}", src)
    assert fn, "expected _renderSources(host, campaignId, items)"
    return fn.group(0)


# ══════════════════════════════════════════════════════════════════════════
# Name field
# ══════════════════════════════════════════════════════════════════════════


def test_name_field_has_inline_explainer_span():
    """Finding #14: the Name field shipped a bare `<label>Name</label>` with
    no explanation of what the field is for. Must now carry an inline
    explainer span, matching the style already used for Daily target/Trying
    new sources."""
    body = _campaign_card_fn(_cs_src())
    label_m = re.search(r'<label class="settings-label" for="cs-name-\$\{id\}">Name[\s\S]*?</label>', body)
    assert label_m, "expected the Name field's <label> block"
    label = label_m.group(0)
    assert "<span" in label, "expected an inline explainer <span> next to the Name label"
    assert "how this search shows up in your list" in label


def test_name_field_input_has_title_tooltip():
    body = _campaign_card_fn(_cs_src())
    input_m = re.search(r'<input id="cs-name-\$\{id\}"[\s\S]*?>', body)
    assert input_m, "expected the Name <input>"
    assert 'title="' in input_m.group(0), "expected a title= tooltip on the Name input"
    assert "doesn't affect what I search for" in input_m.group(0)


# ══════════════════════════════════════════════════════════════════════════
# Run mode
# ══════════════════════════════════════════════════════════════════════════


def test_run_mode_field_has_inline_explainer_span():
    """Finding #14: the Run mode `<select>` had a bare label and no
    explanation of what the three modes mean or when the search stops."""
    body = _campaign_card_fn(_cs_src())
    label_m = re.search(r'<label class="settings-label" for="cs-mode-\$\{id\}">Run mode[\s\S]*?</label>', body)
    assert label_m, "expected the Run mode field's <label> block"
    label = label_m.group(0)
    assert "<span" in label, "expected an inline explainer <span> next to the Run mode label"
    assert "when I stop looking" in label


def test_run_mode_select_has_title_tooltip_explaining_all_three_modes():
    body = _campaign_card_fn(_cs_src())
    select_m = re.search(r'<select id="cs-mode-\$\{id\}"[\s\S]*?>\$\{modeOpts\}</select>', body)
    assert select_m, "expected the Run mode <select>"
    select = select_m.group(0)
    assert 'title="' in select, "expected a title= tooltip on the Run mode select"
    for phrase in ("Continuous", "Fixed duration", "Until enough matches"):
        assert phrase in select, f"expected the tooltip to explain {phrase!r}"


# ══════════════════════════════════════════════════════════════════════════
# Source-toggle checkboxes
# ══════════════════════════════════════════════════════════════════════════


def test_source_toggle_checkbox_row_has_title_tooltip():
    """Finding #12/#14: the discovery-source toggle rows (~lines 195-207)
    rendered a checkbox + brand name + yield stats with no explanation of
    what flipping the toggle actually does."""
    body = _render_sources_fn(_cs_src())
    label_m = re.search(
        r'<label class="settings-row" style="cursor:pointer;align-items:center;gap:8px"[\s\S]*?</label>',
        body,
    )
    assert label_m, "expected the per-source toggle <label> row"
    label = label_m.group(0)
    assert "title=" in label, "expected a title= tooltip on the source-toggle row"
    assert "I search" in label
    assert "kept in case you turn it back on" in label


def test_source_toggle_tooltip_still_precedes_the_checkbox_input():
    """Sanity check that the new tooltip wraps the existing structure rather
    than replacing/reordering it: the checkbox input and its data-cs-source
    attribute must still be present, untouched."""
    body = _render_sources_fn(_cs_src())
    assert '<input type="checkbox" data-cs-source="${key}"' in body


# ══════════════════════════════════════════════════════════════════════════
# Hygiene: syntax + white-label denylist
# ══════════════════════════════════════════════════════════════════════════


def test_node_check_applicant_campaign_settings_js(node_available):
    res = subprocess.run(
        ["node", "--check", str(_CAMPAIGN_SETTINGS_JS)], capture_output=True, timeout=15, text=True
    )
    assert res.returncode == 0, f"node --check failed:\n{res.stderr}"


#: The four upstream-fork codenames CI's repo-wide white-label denylist step
#: bans from shipped artifacts. Split into two-piece tuples so the literal,
#: contiguous codename string never appears in this file's own source text.
_DENYLIST_CODENAME_HALVES = (
    ("fire", "house"),
    ("or", "well"),
    ("odys", "seus"),
    ("smo", "key"),
)


def test_source_file_is_denylist_clean():
    text = _cs_src().lower()
    for a, b in _DENYLIST_CODENAME_HALVES:
        assert (a + b) not in text


def test_new_test_file_is_denylist_clean():
    text = pathlib.Path(__file__).read_text(encoding="utf-8").lower()
    for a, b in _DENYLIST_CODENAME_HALVES:
        assert (a + b) not in text
