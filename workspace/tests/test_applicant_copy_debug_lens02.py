"""Regression coverage for the copy & voice audit
(``docs/design/audits/exhaustive2/02_copy_voice.md``), confined to this pass's
file lane: ``applicantDebug.js`` (the Activity/Debug admin surface).

Copy-only pass: no logic or DOM structure changed, only user-facing strings
(button/label tooltip text, banner text, and toast copy). This file follows
the established convention (``test_applicant_copy_voice_02_documents_digest.py``,
``test_applicant_exhaustive2_gallery_campaignsettings_a11y.py``): every fact is
read from the actual static file content via ``pathlib`` + regex — no browser,
no DOM, no real socket. Each assertion was verified, by hand, to go red when
the underlying fix is reverted (temporarily restore the pre-fix source from a
file-copy backup, rerun, see a real ``AssertionError``, then restore from the
backup — never ``git stash``) before this file was landed.

What this batch fixes (see the audit's "Live takeover, chat, vault, compare,
gallery, debug, nav chrome" section, findings 207/220-222/224/233/234/236/238):

* Finding #236 — "assistant"/"agent" mixed within one tooltip: the "Ask the
  assistant" overflow item's title now names the surface consistently ("Job
  Assistant") instead of switching to "the agent" mid-sentence.
* Finding #221 — the audit-log download error toast no longer surfaces the
  raw ``e.message`` (which can carry an HTTP status / raw server text via the
  ``Unexpected response (${status})`` fallback); it always shows the same
  calm, plain-language line.
* Finding #234 — British "favour" -> "favor" (the only ``-our`` spelling in
  the product) in the Insights conversion-so-far note.
* Finding #238 — "awaiting review" -> "in review" in the Variants approval-
  state label, matching the "in review" wording used elsewhere.
* Finding #222 — "digest" jargon in the Run-now explainer replaced with the
  panel's own name, "Daily updates".
* Finding #224 — "clamped" engineering verb replaced with plain "lowered to
  the cap" in the Run-controls daily-target note.
* Finding #220 — the machine-readable ``res.reason`` enum value can no longer
  reach a toast raw; only the mapped label or the generic fallback shows.
* Finding #233 — the "posting(s)" parenthetical plural in the run-complete
  toast is now a real singular/plural branch.
* Finding #207 — the "Engine offline" banner badge is now "Not connected",
  matching the same fix already landed in applicantGallery.js.

This follow-up batch applies the remaining lens-02 finding that names this
file plus the cross-cutting rules the audit calls out at the top of the
document (first-person-singular "I" wherever the agent speaks, never
"we"/"the assistant"/"Applicant" as the actor; curly apostrophes; raw
``e.message`` toasts routed through the shared ``errText`` helper instead of
shown verbatim):

* Finding #189 — the modal's own heading (mirrored from the nav launcher
  label fix in index.html) is now "Activity & controls", matching the
  settled name used for the aria-labelledby target and the launcher button.
* Cross-cutting #1 (first person) — "What the agent is doing" (Run tab
  headline), the Tools/Background-connection/Captcha-handling sub-section
  intros, and the chat-unavailable toasts no longer speak about "the
  assistant"/"the agent" in the third person; they speak as "I".
* Cross-cutting #2 (raw ``e.message``) — every remaining
  ``_toast(e.message || '...')`` / ``textContent = e.message || '...'``
  pattern in this file (mark-submitted, save-run-settings, run-now,
  pause/resume, source toggle, explore-budget save, tool toggle, update
  trigger, and the application-detail load failure) now routes through the
  shared ``errText()`` helper from applicantCore.js instead of surfacing the
  engine/proxy's raw error text.
* Cross-cutting #3 (curly apostrophes) — every remaining straight apostrophe
  in a user-facing string in this file (the skip-reason labels, the Run
  headline, the variant nudge, the detection-events intro, and the Update
  section's "aren't") is now curly (’).
* The generic offline/gated fallback messages shared by every tab
  (``_renderOffline``'s default, ``_errLine``'s offline branch, and
  ``_renderGated``'s default) drop "The Applicant engine" as the actor and
  speak in the first person, matching the equivalent fixes already landed
  elsewhere (applicantCompare.js/applicantGallery.js finding #205/#206,
  applicantPortal.js finding #13).
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
JS_DIR = REPO_ROOT / "workspace" / "static" / "js"
DEBUG_JS = JS_DIR / "applicantDebug.js"

_HAS_NODE = shutil.which("node") is not None


@pytest.fixture(scope="module")
def node_available():
    if not _HAS_NODE:
        pytest.skip("node binary not on PATH")


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _find_function(src: str, name: str) -> str:
    """Extract a top-level `function name(...) { ... }` body via brace
    counting (mirrors test_applicant_copy_voice_02_documents_digest.py's
    helper)."""
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


def test_node_check_applicant_debug_js(node_available):
    res = subprocess.run(["node", "--check", str(DEBUG_JS)], capture_output=True, timeout=15, text=True)
    assert res.returncode == 0, f"node --check failed:\n{res.stderr}"


def test_ask_assistant_tooltip_names_one_surface_not_two():
    """Finding #236 — the tooltip used to switch from "the assistant" to
    "the agent" mid-sentence; it must now name the Job Assistant once."""
    src = _read(DEBUG_JS)
    assert 'title="Open the assistant beside this so you can ask about what the agent is doing"' not in src
    assert "Job Assistant" in src
    assert "title=\"Open the Job Assistant beside this window to ask about what’s happening\"" in src


def test_download_audit_log_error_toast_drops_raw_message():
    """Finding #221 — the raw HTTP-status / server-text error must not reach
    the toast; only the calm, plain-language fallback should show."""
    body = _find_function(_read(DEBUG_JS), "_downloadAuditLog")
    assert re.search(r"catch\s*\(e\)\s*\{\s*_toast\('Could not download the activity log right now\.'\);", body), (
        "expected the catch block to always show the plain-language message"
    )
    assert "_toast(e.message" not in body


def test_insights_conversion_note_uses_american_spelling():
    """Finding #234 — the only -our spelling in the product."""
    src = _read(DEBUG_JS)
    assert "favour" not in src
    assert "which sources and roles to favor next" in src


def test_variant_approval_state_is_in_review_not_awaiting():
    """Finding #238."""
    body = _find_function(_read(DEBUG_JS), "_renderVariants")
    assert "'awaiting review'" not in body
    assert "'in review'" in body


def test_run_now_explainer_says_daily_updates_not_digest():
    """Finding #222 — the surface is called Daily updates, not "the digest"."""
    src = _read(DEBUG_JS)
    assert "refreshes the digest" not in src
    assert "refreshes your Daily updates" in src


def test_run_target_note_drops_clamped_jargon():
    """Finding #224."""
    src = _read(DEBUG_JS)
    assert "are clamped automatically" not in src
    assert "are lowered to the cap automatically" in src


def test_run_now_skip_reason_never_shows_raw_machine_value():
    """Finding #220 — the raw ``res.reason`` enum (e.g. "prefill_locked")
    must never itself reach the toast; only the mapped label or the
    generic fallback can."""
    src = _read(DEBUG_JS)
    assert not re.search(r"_SKIP_REASON_LABELS\[res\.reason\]\s*\|\|\s*res\.reason\s*\|\|", src), (
        "raw res.reason must not be a toast fallback"
    )
    assert "_SKIP_REASON_LABELS[res.reason] || 'Nothing to run right now.'" in src


def test_run_now_found_count_uses_real_plural():
    """Finding #233 — no bare "(s)" parenthetical plural."""
    src = _read(DEBUG_JS)
    assert "posting(s)" not in src
    assert "res.discovered === 1 ? 'posting' : 'postings'" in src


def test_engine_banner_says_not_connected():
    """Finding #207 — matches the fix already landed in applicantGallery.js
    (finding #207 there too)."""
    fn = re.search(r"function _setEngineBanner\(modal, up\)\s*\{(.*?)\n\}", _read(DEBUG_JS), re.S)
    assert fn, "expected _setEngineBanner"
    assert "Engine offline" not in fn.group(1)
    assert "Not connected" in fn.group(1)


def test_modal_heading_matches_settled_launcher_name():
    """Finding #189 — the launcher/nav button became "Activity & controls";
    the modal's own on-screen heading (the aria-labelledby target) must match
    it instead of just "Activity"."""
    src = _read(DEBUG_JS)
    assert re.search(r'id="applicant-debug-title">\s*<svg[^<]*<[^<]*</svg>\s*Activity &amp; controls\s*</h4>', src), (
        "expected the modal heading text to read 'Activity & controls'"
    )


def test_run_headline_speaks_in_first_person_not_about_the_agent():
    """Cross-cutting #1 — "What the agent is doing" third-persons the agent
    on its own headline; it must say "I"."""
    src = _read(DEBUG_JS)
    assert "'What the agent is doing'" not in src
    assert "'What I’m doing'" in src


def test_tools_bridge_captcha_intros_speak_in_first_person():
    """Cross-cutting #1 — the Tools/Background-connection/Captcha-handling
    Config sub-section intros used to describe "the assistant" in the third
    person; they now speak as "I"/"my"."""
    src = _read(DEBUG_JS)
    assert "the assistant's tools" not in src
    assert "Turn my tools on or off. I never use a disabled tool." in src
    assert "the assistant's background link" not in src
    assert "Whether my background link to this workspace" in src
    assert "How the assistant handles a captcha" not in src
    assert "How I handle a captcha I run into while filling out an application." in src


def test_chat_unavailable_toasts_speak_in_first_person():
    """Cross-cutting #1 — the Job-Assistant-unavailable fallback toasts used
    to name "the assistant" in the third person."""
    src = _read(DEBUG_JS)
    assert "_toast('The assistant is not available right now.')" not in src
    assert "_toast('I’m not available right now.')" in src
    assert "_toast('Could not open the assistant.')" not in src
    assert "_toast('I couldn’t open the assistant.')" in src


def test_generic_offline_and_gated_fallbacks_speak_in_first_person():
    """The shared offline/gated fallback messages (used by every tab) must
    not name "The Applicant engine" as the actor, matching the equivalent
    fixes already landed in applicantCompare.js/applicantGallery.js/
    applicantPortal.js."""
    src = _read(DEBUG_JS)
    assert "The Applicant engine is not reachable right now" not in src
    assert src.count("I can’t connect right now. This view will fill in once I’m back.") >= 2
    assert "Finish onboarding and configure your model and notification channels to enable automated work." not in src
    assert "Finish setup — connect a model and fill in your profile — and I can start working for you." in src


def test_remaining_raw_e_message_toasts_route_through_err_text():
    """Cross-cutting #2 — every remaining ``_toast(e.message || '...')`` /
    ``textContent = e.message || '...'`` pattern in this file must be gone;
    each now calls the shared ``errText()`` helper instead."""
    src = _read(DEBUG_JS)
    assert not re.search(r"_toast\(e\.message", src)
    assert not re.search(r"textContent = e\.message", src)
    assert not re.search(r"_empty\(anyErr\.message", src)
    # Spot-check a representative fix in each function that had one.
    assert "_toast(errText(e));" in src
    assert "if (msg) msg.textContent = errText(e);" in src
    assert "if (out) out.textContent = errText(e);" in src
    assert "${_empty(errText(anyErr))}" in src


def test_remaining_user_facing_apostrophes_are_curly():
    """Cross-cutting #3 — spot-check every straight apostrophe this batch
    fixed in a genuinely user-facing string (not a code comment)."""
    src = _read(DEBUG_JS)
    assert "Today's application limit is reached — it'll resume tomorrow." not in src
    assert "Today’s application limit is reached — it’ll resume tomorrow." in src
    assert "hasn't yet — consider using" not in src
    assert "hasn’t yet — consider using" in src
    assert "job search's automated browsing" not in src
    assert "job search’s automated browsing" in src
    assert "updates aren't enabled on this install" not in src
    assert "updates aren’t enabled on this install" in src
    assert "this view will fill in once I\\'m connected" not in src
    assert "this view will fill in once I’m connected" in src


# ── Denylist hygiene (per the task's standing instruction) ──────────────────

#: The four upstream-fork codenames CI's repo-wide white-label denylist step
#: bans from shipped artifacts. Split into two-piece tuples so the literal,
#: contiguous codename string never appears in this file's own source text.
_DENYLIST_CODENAME_HALVES = (
    ("fire", "house"),
    ("or", "well"),
    ("odys", "seus"),
    ("smo", "key"),
)


def test_new_test_file_is_denylist_clean():
    text = pathlib.Path(__file__).read_text(encoding="utf-8").lower()
    for a, b in _DENYLIST_CODENAME_HALVES:
        assert (a + b) not in text
