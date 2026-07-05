"""Regression coverage for the copy & voice audit
(``docs/design/audits/exhaustive2/02_copy_voice.md``), confined to this batch's
three owned surfaces: ``applicantCompare.js``, ``applicantModelLadder.js``,
``applicantActivity.js``.

This is a copy-only pass: plain-language strings, one house voice
(first-person-singular, calm, no engineering vocabulary, no third-person
self-reference), consistent terminology ("job search" not "campaign", "IDs"
not "ids", "levels" not "ladder"/"tier"), and warmer error/empty-state copy.
No DOM/logic changes.

Follows the established convention (test_applicant_backlog_warmempty.py,
test_applicant_help_selfexplain_12.py): every fact is read from the actual
static file content via ``pathlib`` (+ light string checks) — no browser, no
DOM, no real socket. Each assertion here was verified, by hand, to go red
when the underlying fix is reverted (temporarily restored the pre-fix source
from a file-copy backup, reran, saw a real ``AssertionError``, then restored
from the backup — never ``git stash``) before this file was landed.
"""

from __future__ import annotations

import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
JS_DIR = REPO_ROOT / "workspace" / "static" / "js"

COMPARE_JS = JS_DIR / "applicantCompare.js"
MODEL_LADDER_JS = JS_DIR / "applicantModelLadder.js"
ACTIVITY_JS = JS_DIR / "applicantActivity.js"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# ── applicantCompare.js (audit items #184-186, #205, #229-231) ──────────────


def test_compare_drops_campaign_jargon_for_job_search():
    js = _read(COMPARE_JS)
    assert "Job search (optional)" in js
    assert "All job searches" in js
    assert "Campaign (optional scope)" not in js
    assert "<option value=\"\">All campaigns</option>" not in js


def test_compare_hint_drops_engine_and_campaign_jargon():
    js = _read(COMPARE_JS)
    assert "Add two or more IDs from the same job search." in js
    assert "The engine needs two or more ids from the same campaign." not in js


def test_compare_offline_error_is_plain_and_first_person():
    js = _read(COMPARE_JS)
    assert "I can't connect right now. Try again in a moment." in js
    assert "The Applicant engine is not reachable right now" not in js


def test_compare_ids_casing_is_capitalized_throughout():
    js = _read(COMPARE_JS)
    assert "IDs to compare" in js
    assert "One ID per line, or comma-separated" in js
    assert "Enter at least two IDs to compare." in js
    assert "Ids to compare" not in js
    assert "Enter at least two ids to compare." not in js


def test_compare_dimension_column_renamed_field():
    js = _read(COMPARE_JS)
    assert "<tr><th>Field</th>" in js
    assert "<tr><th>Dimension</th>" not in js


def test_compare_difference_tooltip_drops_engine_jargon():
    js = _read(COMPARE_JS)
    assert "A short note on what actually differs for this row" in js
    assert "A short note from the engine on what actually differs" not in js


def test_compare_copy_id_tooltip_capitalized():
    js = _read(COMPARE_JS)
    assert 'title="Copy ID — ' in js
    assert 'title="Copy id — ' not in js


# ── applicantModelLadder.js (audit items #44-45, #64-68) ────────────────────


def test_model_ladder_endpoint_url_renamed_server_address():
    js = _read(MODEL_LADDER_JS)
    assert ">Server address" in js
    assert ">Endpoint URL" not in js


def test_model_ladder_remove_button_says_level_not_tier():
    js = _read(MODEL_LADDER_JS)
    assert 'title="Remove this level" aria-label="Remove this level"' in js
    assert "Remove this tier" not in js
    assert 'aria-label="Remove tier"' not in js


def test_model_ladder_save_button_says_levels_not_ladder():
    js = _read(MODEL_LADDER_JS)
    # Both the rendered button and its post-failure textContent reset.
    assert js.count("Save levels") >= 2
    assert "Save ladder" not in js


def test_model_ladder_explainer_is_first_person():
    js = _read(MODEL_LADDER_JS)
    assert "I start at <strong>Level 1</strong> and climb to a higher level" in js
    assert "Applicant starts at <strong>Level 1</strong>" not in js


def test_model_ladder_offline_note_is_first_person_no_engine_jargon():
    js = _read(MODEL_LADDER_JS)
    assert "I can't reach my back end right now" in js
    assert "open this again in a moment to edit your model levels" in js
    assert "The application engine is offline" not in js


def test_model_ladder_save_toast_teaches_not_just_confirms():
    js = _read(MODEL_LADDER_JS)
    assert "Saved. I'll start at Level 1 and step up only when a task needs more." in js
    assert "Saved a " not in js  # the old `${_tiers.length}-level model ladder` toast


def test_model_ladder_error_fallbacks_are_first_person():
    js = _read(MODEL_LADDER_JS)
    assert "I couldn't save your levels." in js
    assert "I couldn't load your model levels. Reload to try again." in js
    assert "Could not save the model ladder." not in js
    assert "Could not load the model ladder." not in js


def test_model_ladder_saved_connections_note_drops_engine_jargon():
    js = _read(MODEL_LADDER_JS)
    assert "Other model connections I've found or been given, separate from the levels above." in js
    assert "the engine has discovered" not in js
    assert "separate from the ladder above" not in js


def test_model_ladder_routing_fallback_says_level_not_ladder():
    js = _read(MODEL_LADDER_JS)
    assert "requests fall back to the level order above." in js
    assert "requests fall back to the ladder order above." not in js


# ── applicantActivity.js (audit items #139-141, #146, #150-155, #174) ───────


def test_activity_status_strip_drops_applicant_is_colon_construction():
    js = _read(ACTIVITY_JS)
    assert "Applicant is:" not in js


def test_activity_reconnecting_copy_is_terse_not_third_person():
    js = _read(ACTIVITY_JS)
    assert "text.textContent = 'Reconnecting…';" in js
    assert "strip.title = 'Reconnecting — open Activity';" in js


def test_activity_pause_confirm_is_first_person():
    js = _read(ACTIVITY_JS)
    assert "Pause all automated work? I'll stop everything until you resume." in js
    assert "Your assistant stops until you resume." not in js


def test_activity_pause_toggle_aria_is_first_person():
    js = _read(ACTIVITY_JS)
    assert "Pause me — I'll stop all automated work" in js
    assert "Resume me — I'll restart automated work" in js
    assert "Pause your assistant" not in js
    assert "Resume your assistant" not in js


def test_activity_empty_state_is_first_person():
    js = _read(ACTIVITY_JS)
    assert "I'm getting ready. As soon as I start " in js
    assert "everything I do shows up here." in js
    assert "your assistant is getting ready" not in js


def test_activity_offline_note_is_first_person():
    js = _read(ACTIVITY_JS)
    assert "My activity will appear here once I'm connected and running." in js
    assert "Your assistant's activity will appear here" not in js


def test_activity_gated_fallback_matches_portal_style_rewrite():
    js = _read(ACTIVITY_JS)
    assert (
        "Finish setup — connect a model and fill in your profile — and I can "
        "start working for you." in js
    )
    assert "Finish onboarding and configure your model and notification channels" not in js


def test_activity_snapshot_heading_drops_agent_jargon():
    js = _read(ACTIVITY_JS)
    assert "Right now</div>" in js
    assert "Agent status</div>" not in js


def test_activity_stat_summary_labels_are_lowercase_past_tense():
    js = _read(ACTIVITY_JS)
    assert "push(stats.discovered, 'discovered');" in js
    assert "push(stats.pipelines_started, 'pre-filled');" in js
    assert "push(stats.completed, 'submitted');" in js
    assert "'Discovered'" not in js
    assert "'pre-filling'" not in js
    assert "push(stats.completed, 'completed');" not in js


def test_activity_budget_line_avoids_internal_rationing_jargon():
    js = _read(ACTIVITY_JS)
    assert "${budget} more I can send today" in js
    assert "left in today's budget" not in js


# ── node --check on every touched file (CI-equivalent front-end syntax gate)


def test_node_check_all_touched_files():
    import shutil
    import subprocess

    if shutil.which("node") is None:
        import pytest
        pytest.skip("node binary not on PATH")
    for path in (COMPARE_JS, MODEL_LADDER_JS, ACTIVITY_JS):
        res = subprocess.run(
            ["node", "--check", str(path)],
            capture_output=True, text=True, timeout=15,
        )
        assert res.returncode == 0, f"node --check failed for {path.name}:\n{res.stderr}"
