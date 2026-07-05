"""Regression coverage for the help/self-explanation audit
(``docs/design/audits/exhaustive2/12_help_selfexplain.md``), confined to this
batch's file lane: ``applicantOnboarding.js``, ``applicantCompare.js``,
``applicantModelLadder.js``, ``applicantActivity.js``, and
``emailLibrary/applicantDigest.js``.

Follows the established convention (``test_applicant_backlog_referralprompt.py``,
``test_applicant_round2_wave2_firstlight.py``): every fact is read from the
actual static file content via ``pathlib`` + regex — no browser, no DOM, no
real socket. Each assertion was verified, by hand, to go red when the
underlying fix is reverted (temporarily restore the pre-fix source from a
file-copy backup, rerun, see a real ``AssertionError``, then restore from the
backup — never ``git stash``) before this file was landed.

What this batch adds:

* item 23 — the OOBE send-off toast now teaches the daily cadence (continuous
  search, digest arrives on its own, Pending holds anything needing a
  decision) instead of a bare "getting to work" line.
* item 22 — a first-open, dismissible card in the digest panel teaches the
  approve/pass feedback loop before the user's first decision, persisted via
  a localStorage flag matching this session's ``applicant_`` key convention.
* item 13 (tooltip census) — a few of the lowest-coverage surfaces
  (Compare, the model ladder's saved-connections + context-window field,
  Activity's run-history heading) gain plain-language `title=` tooltips on
  controls/labels that previously had none, reusing the existing
  `title=`-only tooltip pattern rather than inventing new UI.
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
JS_DIR = REPO_ROOT / "workspace" / "static" / "js"
ONBOARDING_JS = JS_DIR / "applicantOnboarding.js"
COMPARE_JS = JS_DIR / "applicantCompare.js"
MODEL_LADDER_JS = JS_DIR / "applicantModelLadder.js"
ACTIVITY_JS = JS_DIR / "applicantActivity.js"
DIGEST_JS = JS_DIR / "emailLibrary" / "applicantDigest.js"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _find_function(src: str, name: str) -> str:
    """Extract a top-level `function name(...) { ... }` body via brace
    counting (mirrors test_applicant_round2_wave2_firstlight.py's helper)."""
    m = re.search(rf"function {re.escape(name)}\([^)]*\)\s*\{{", src)
    assert m, f"expected to find function {name}"
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


# ── item 23: OOBE send-off teaches the daily cadence ────────────────────────


def test_home_base_handoff_teaches_continuous_search():
    body = _find_function(_read(ONBOARDING_JS), "_openHomeBaseAfterSetup")
    assert "all set" in body.lower()
    assert "home base" in body.lower()
    assert re.search(r"around the clock|continuous", body, re.IGNORECASE), (
        "expected the send-off to say the assistant searches continuously, "
        "not just 'getting to work'"
    )


def test_home_base_handoff_mentions_digest_and_pending():
    body = _find_function(_read(ONBOARDING_JS), "_openHomeBaseAfterSetup")
    assert "digest" in body.lower(), (
        "expected the send-off to mention the digest arriving on its own"
    )
    assert "Pending" in body, (
        "expected the send-off to say decisions wait in Pending, matching the "
        "Portal's own vocabulary"
    )


def test_home_base_handoff_keeps_multisecond_toast_duration():
    """Guard against regressing the pre-existing fix this batch builds on:
    the toast must still give a multi-second window to read the longer copy."""
    body = _find_function(_read(ONBOARDING_JS), "_openHomeBaseAfterSetup")
    assert re.search(r"duration:\s*[3-9]\d{3}", body), (
        "expected a multi-second toast duration, not the terse default"
    )


def test_home_base_handoff_still_has_offline_fallback_toast():
    """The `_toast(...)` fallback path (used when uiModule.showToast is
    unavailable) must still exist and stay short/safe."""
    body = _find_function(_read(ONBOARDING_JS), "_openHomeBaseAfterSetup")
    assert "_toast(" in body


# ── item 22: digest first-open feedback-loop intro card ─────────────────────


def test_loop_intro_seen_key_follows_applicant_naming_convention():
    src = _read(DIGEST_JS)
    assert "LOOP_INTRO_SEEN_KEY = 'applicant_digest_loop_intro_seen'" in src, (
        "expected a localStorage key matching this file's applicant_ prefix "
        "convention (REFERRAL_DISMISSED_KEY, LAST_CAMPAIGN_KEY)"
    )


def test_loop_intro_html_helper_is_gated_on_seen_state():
    body = _find_function(_read(DIGEST_JS), "_loopIntroHTML")
    assert re.search(r"if\s*\(\s*_isLoopIntroSeen\(\)\s*\)\s*return\s*'';", body), (
        "the intro must render nothing once the user has dismissed it — "
        "otherwise it would show on every open forever"
    )


def test_loop_intro_copy_teaches_the_approve_pass_feedback_loop():
    body = _find_function(_read(DIGEST_JS), "_loopIntroHTML")
    assert "tunes what tomorrow's digest contains" in body
    assert "passing with a reason" in body
    assert "Got it" in body, "expected a dismiss button labelled plainly, not a bare X"


def test_loop_intro_reuses_existing_card_and_button_classes_not_new_css():
    body = _find_function(_read(DIGEST_JS), "_loopIntroHTML")
    assert "admin-card" in body, "must reuse the existing admin-card look"
    assert "memory-toolbar-btn" in body, (
        "the dismiss button must reuse the existing toolbar-button class, "
        "matching every other button in this panel"
    )


def test_dismiss_helper_persists_to_localstorage_and_removes_the_card():
    body = _find_function(_read(DIGEST_JS), "_dismissLoopIntro")
    assert "localStorage.setItem(LOOP_INTRO_SEEN_KEY" in body
    assert "el.remove()" in body, (
        "dismissing must remove the card from the currently-rendered panel "
        "immediately, not just persist the flag for next time"
    )


def test_ensure_panel_actually_renders_the_intro_card():
    """Reachability: _loopIntroHTML() must be called from the panel template,
    not just exist as unused dead code."""
    src = _read(DIGEST_JS)
    ensure_panel = _find_function(src, "_ensurePanel")
    assert "_loopIntroHTML()" in ensure_panel


def test_wire_binds_the_dismiss_button():
    """Reachability: the dismiss button rendered by _loopIntroHTML() must
    actually get a click handler wired in _wire(panel)."""
    body = _find_function(_read(DIGEST_JS), "_wire")
    assert "applicant-digest-loop-intro-dismiss" in body
    assert "_dismissLoopIntro(panel)" in body


def test_loop_intro_never_makes_a_network_call():
    """Purely client-side, like the referral nudge it mirrors — no new proxy
    route, no new engine call."""
    src = _read(DIGEST_JS)
    fns = "".join([
        _find_function(src, "_isLoopIntroSeen"),
        _find_function(src, "_dismissLoopIntro"),
        _find_function(src, "_loopIntroHTML"),
    ])
    assert "fetch(" not in fns
    assert "_api(" not in fns


# ── item 13 (tooltip census): Compare gains explanatory tooltips ────────────


def test_compare_kind_select_explains_applications_vs_postings():
    src = _read(COMPARE_JS)
    m = re.search(r'<select id="applicant-compare-kind"[^>]*>', src)
    assert m, "expected the compare-kind select"
    assert "title=" in m.group(0), (
        "expected a title= tooltip distinguishing Applications from Postings, "
        "matching this file's existing title=-only tooltip pattern"
    )


def test_compare_difference_column_header_has_a_tooltip():
    src = _read(COMPARE_JS)
    assert re.search(
        r'<th title="[^"]*differ[^"]*">Difference</th>', src,
    ), "expected the Difference column header to explain what it shows"


# ── item 13 (tooltip census): model ladder gains explanatory tooltips ───────


def test_model_ladder_context_window_label_has_a_tooltip():
    body = _find_function(_read(MODEL_LADDER_JS), "_tierRowHTML")
    assert re.search(
        r'title="[^"]*"[^>]*>Context window', body,
    ), "expected the Context window label to gain a plain-language title= tooltip"


def test_model_ladder_saved_endpoint_buttons_have_tooltips():
    body = _find_function(_read(MODEL_LADDER_JS), "_savedEndpointsHTML")
    assert re.search(r"ml-ep-toggle[^>]*title=", body), (
        "expected the Enable/Disable button to explain it doesn't delete the connection"
    )
    assert re.search(r"ml-ep-remove[^>]*title=", body), (
        "expected the Remove button to explain it permanently deletes the connection"
    )


# ── item 13 (tooltip census): Activity's run-history heading ────────────────


def test_activity_recently_heading_explains_what_a_run_is():
    body = _find_function(_read(ACTIVITY_JS), "_renderRuns")
    assert re.search(r'title="[^"]*pass[^"]*"', body), (
        "expected the 'Recently I…' heading to gain a tooltip explaining each "
        "row is one pass the assistant took"
    )


# ── node --check on every touched file (CI-equivalent front-end syntax gate)


def test_node_check_all_touched_files(node_available=None):
    import shutil
    import subprocess

    if shutil.which("node") is None:
        import pytest
        pytest.skip("node binary not on PATH")
    for path in (ONBOARDING_JS, COMPARE_JS, MODEL_LADDER_JS, ACTIVITY_JS, DIGEST_JS):
        res = subprocess.run(
            ["node", "--check", str(path)],
            capture_output=True, text=True, timeout=15,
        )
        assert res.returncode == 0, f"node --check failed for {path.name}:\n{res.stderr}"
