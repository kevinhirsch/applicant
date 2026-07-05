"""Regression coverage for the copy & voice audit
(``docs/design/audits/exhaustive2/02_copy_voice.md``), confined to this pass's
file lane: ``documentLibrary.js`` (the Applications tab / redline review) and
``emailLibrary/applicantDigest.js`` (the Daily updates panel).

Copy-only pass: no logic or DOM structure changed, only user-facing strings
(button/label text, tooltips, toasts, empty/error states). This file follows
the established convention (``test_applicant_help_selfexplain_12.py``,
``test_applicant_exhaustive2_gallery_campaignsettings_a11y.py``): every fact
is read from the actual static file content via ``pathlib`` + regex — no
browser, no DOM, no real socket. Each assertion was verified, by hand, to go
red when the underlying fix is reverted (temporarily restore the pre-fix
source from a file-copy backup, rerun, see a real ``AssertionError``, then
restore from the backup — never ``git stash``) before this file was landed.

What this batch fixes (see the audit's "Daily digest + redline review"
section, findings 85-137):

* Third-person self-reference ("the assistant", "your job-search assistant")
  replaced with first-person "I" throughout both surfaces — approve/pass/
  research/feedback/survey tooltips and toasts, the panel intro, the
  empty-day note, the loop-intro teaser, and the redline-review action row.
* "application engine" / "the engine" jargon in status lines and error
  copy dropped in favor of plain "I couldn't connect" / "connected" /
  "Checking the connection…" language (documentLibrary.js).
* "resume variant(s)" standardized to "resume version(s)" in the variant-
  library lookup form, its loading/empty states, and the approval-state
  label ("awaiting review" -> "needs review", matching the "Needs review"
  gate badge already used one panel over).
* Raw ``Request failed (${status})`` / cold "Could not X right now." system-
  voice toasts replaced with a calm, plain-language, guidance-bearing form
  across both files (approve/pass/bulk actions, research, feedback, survey,
  digest load, alignment lookup) instead of only the exact wording quoted in
  the audit's "before" text — the same cold pattern repeats at several
  additional call sites within these two files, and leaving some fixed and
  some not would itself be a voice-consistency regression the audit's own
  cross-cutting rule #1/#2 calls out.
* Assorted single-instance fixes: "Show materials"/"Show variants" buttons,
  "Review & edit" ampersand, the "Working…" busy-label on the change-request
  button, the redline's unexplained +/- legend, research-brief jargon
  ("research run" -> "research brief") in the report modal, the referral-
  adjacent "Keep" cancel label naming what it keeps, and the to-do-list
  grammar bug in the post-survey toast.
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
JS_DIR = REPO_ROOT / "workspace" / "static" / "js"
DOCLIB_JS = JS_DIR / "documentLibrary.js"
DIGEST_JS = JS_DIR / "emailLibrary" / "applicantDigest.js"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _find_function(src: str, name: str) -> str:
    """Extract a top-level `function name(...) { ... }` body via brace
    counting (mirrors test_applicant_help_selfexplain_12.py's helper, itself
    from test_applicant_round2_wave2_firstlight.py). Works for functions
    nested inside a larger enclosing function/IIFE too, since it just
    locates the substring "function NAME(" and brace-matches from there."""
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


# ═══════════════════════════════════════════════════════════════════════
# documentLibrary.js — Applications tab / redline review
# ═══════════════════════════════════════════════════════════════════════


def test_generation_status_messages_drop_application_engine_jargon():
    body = _find_function(_read(DOCLIB_JS), "_renderLibApplicant")
    assert "application engine" not in body
    assert body.count("I couldn’t connect just now. Try again shortly.") >= 4, (
        "expected the cover-letter / screening-answer / template-fill / "
        "initial-connection failure paths to all use the same plain-"
        "language connection-failure copy"
    )


def test_materials_status_line_drops_engine_jargon():
    body = _find_function(_read(DOCLIB_JS), "_renderLibApplicant")
    assert "Checking the connection…" in body
    assert "Checking the application engine" not in body
    assert "'connected'" in body or '"connected"' in body
    assert "engine ready" not in body


def test_screening_question_prompt_is_first_person():
    body = _find_function(_read(DOCLIB_JS), "_renderLibApplicant")
    assert "What screening question should I answer?" in body
    assert "the assistant answer" not in body


def test_show_materials_button_renamed_show_documents():
    body = _find_function(_read(DOCLIB_JS), "_renderLibApplicant")
    assert "Show documents</button>" in body
    assert "Show materials" not in body


def test_variant_lookup_form_uses_versions_not_variants():
    body = _find_function(_read(DOCLIB_JS), "_renderLibApplicant")
    assert "Resume versions — the different takes on your resume" in body
    assert "Show versions</button>" in body
    assert "resume versions you want to see" in body
    assert "Show the resume versions tried for this job search." in body
    assert "Enter a job-search ID to see its resume versions." in body
    # "variant" still legitimately appears in internal ids/dataset keys
    # (e.g. `doclib-variant-campaign`, `_variantLastCampaign`) — only the
    # user-facing "resume variant(s)" phrase should be gone.
    assert "resume variants" not in body
    assert "Show variants" not in body


def test_draft_generation_intro_is_first_person_and_reassures_before_use():
    body = _find_function(_read(DOCLIB_JS), "_renderLibApplicant")
    assert (
        "I’ll draft a document for this application — it comes to "
        "you for review before it’s ever used." in body
    )
    assert "before it is ever used" not in body


def test_applications_tab_description_is_first_person_and_says_documents():
    src = _read(DOCLIB_JS)
    assert (
        "Resumes and cover letters I tailor for your job applications. Open "
        "one to review my suggested changes, ask for tweaks, then approve "
        "it before it's used." in src
    )
    assert "Tailored resumes and cover letters generated" not in src


def test_no_tailored_documents_empty_state_is_first_person():
    body = _find_function(_read(DOCLIB_JS), "_loadApplicantMaterials")
    assert (
        "No tailored documents for this application yet. They appear here "
        "once I've drafted them." in body
    )
    assert "No tailored materials" not in body
    assert "the engine has generated them" not in body


def test_error_text_helper_drops_raw_http_status():
    body = _find_function(_read(DOCLIB_JS), "_applicantErrText")
    assert "Request failed" not in body
    assert "That didn't go through (error " in body
    assert "Try again shortly." in body


def test_variant_library_uses_versions_language():
    body = _find_function(_read(DOCLIB_JS), "_loadVariantLibrary")
    assert "Loading resume versions…" in body
    assert (
        "I haven’t tried any resume versions for this job search yet."
        in body
    )
    assert "resume variants" not in body
    assert "application engine" not in body
    assert "I couldn’t connect just now. Try again shortly." in body


def test_variant_approval_state_matches_needs_review_badge():
    body = _find_function(_read(DOCLIB_JS), "_loadVariantLibrary")
    assert "'needs review'" in body
    assert "'awaiting review'" not in body


def test_company_research_badge_tooltip_is_first_person():
    body = _find_function(_read(DOCLIB_JS), "_loadResearchProvenance")
    assert (
        "I looked up the company before writing this — it informed "
        "the wording below." in body
    )
    assert "The assistant looked up" not in body


def test_redline_review_change_request_copy_is_first_person():
    body = _find_function(_read(DOCLIB_JS), "_renderApplicantReview")
    assert "I’ll revise the document and show the result here." in body
    assert "The engine revises the document" not in body
    assert "Ask me to make this change — I’ll show the updated draft here." in body
    assert "Send this change request to the engine." not in body


def test_kind_selector_tooltip_explains_the_choices():
    body = _find_function(_read(DOCLIB_JS), "_renderApplicantReview")
    assert (
        "Pick how to change it — give me exact text to add or remove, "
        "or describe the change and I’ll work it in." in body
    )
    assert "Choose whether to add text, remove text, or just describe a change." not in body


def test_redline_fallback_legend_explains_plus_minus():
    body = _find_function(_read(DOCLIB_JS), "_renderApplicantReview")
    assert (
        "Suggested changes — lines with + are text I'd add, "
        "− is text I'd remove" in body
    )


def test_request_change_busy_label_is_task_specific():
    body = _find_function(_read(DOCLIB_JS), "_renderApplicantReview")
    assert "Making the change…" in body
    assert "'Working…'" not in body


def test_approve_and_decline_tooltips_are_first_person():
    body = _find_function(_read(DOCLIB_JS), "_renderApplicantReview")
    assert "Approve this document — I’ll use it for the application." in body
    assert "Decline this draft — it stays unapproved and won’t be sent." in body
    assert "Approve this document so it can be used" not in body
    assert "Reject this draft." not in body


def test_review_button_label_drops_ampersand():
    body = _find_function(_read(DOCLIB_JS), "_applicantCard")
    assert "'Review and edit'" in body
    assert "Review & edit" not in body


# ═══════════════════════════════════════════════════════════════════════
# emailLibrary/applicantDigest.js — Daily updates panel
# ═══════════════════════════════════════════════════════════════════════


def test_panel_header_and_toolbar_tooltips_are_first_person():
    body = _find_function(_read(DIGEST_JS), "_ensurePanel")
    assert (
        "Roles I flagged for you today. I email you this same summary "
        "— act on anything right here." in body
    )
    assert "your job-search assistant flagged" not in body
    assert 'title="Send me a quick note about my suggestions"' in body
    assert 'title="Answer a few quick questions to help me tune what I send"' in body
    assert "Preview today's update exactly as it will be emailed to you" in body
    assert "the assistant" not in body


def test_loop_intro_copy_is_first_person():
    body = _find_function(_read(DIGEST_JS), "_loopIntroHTML")
    assert "teaches me fastest" in body
    assert "teaches the assistant fastest" not in body


def test_empty_day_note_is_first_person_and_plain_language():
    body = _find_function(_read(DIGEST_JS), "_renderDigest")
    assert (
        "No new roles cleared the bar today. I'm still looking, and I'll "
        "let you know." in body
    )
    assert "The assistant keeps looking" not in body
    assert "I looked at: ${searched}." in body
    assert "Searched: ${searched}." not in body


def test_digest_row_tooltips_are_first_person():
    body = _find_function(_read(DIGEST_JS), "buildDigestRow")
    assert "How well this role fits what you've told me" in body
    assert "Why I suggested this" in body
    assert (
        "Greenlight this role — I'll prepare the application, and "
        "you'll review it before anything is sent" in body
    )
    assert (
        "Skip this role and tell me why — it helps me choose better "
        "next time" in body
    )
    assert "Get a quick research brief on this company and role" in body
    assert 'title: \'Run a quick background-research brief on this company/role\'' not in body
    assert "the assistant" not in body


def test_approve_and_pass_use_plain_language_first_person_toasts():
    src = _read(DIGEST_JS)
    approve_body = _find_function(src, "_onApprove")
    pass_body = _find_function(src, "_onPass")
    assert "I can't approve this one yet — it's still being prepared. Try again shortly." in approve_body
    assert "Approved — I'll take it from here. You'll still review everything before it's sent." in approve_body
    assert "I couldn't approve that just now — try again in a moment." in approve_body
    assert "This role is not ready to approve yet." not in approve_body

    assert "I can't act on this one yet — it's still being prepared." in pass_body
    assert "teaches me what to skip next time" in pass_body
    assert "Add a short reason so I can learn from it." in pass_body
    assert "'Keep this role'" in pass_body
    assert "I couldn't save that just now — try again in a moment." in pass_body
    assert "the assistant" not in pass_body
    assert "This role is not ready to act on yet." not in pass_body


def test_bulk_actions_reuse_the_same_first_person_voice():
    src = _read(DIGEST_JS)
    bulk_approve = _find_function(src, "_onBulkApprove")
    bulk_decline = _find_function(src, "_onBulkDecline")
    assert "I couldn't approve those roles — try again in a moment." in bulk_approve
    assert "Could not approve the selected roles." not in bulk_approve

    assert "teaches me what to skip next time" in bulk_decline
    assert "'Keep these roles'" in bulk_decline
    assert "Add a short reason so I can learn from it." in bulk_decline
    assert "I couldn't save that just now — try again in a moment." in bulk_decline
    assert "the assistant" not in bulk_decline


def test_request_failed_raw_status_replaced_everywhere():
    src = _read(DIGEST_JS)
    api_body = _find_function(src, "_api")
    api_research_body = _find_function(src, "_apiResearch")
    alignment_body = _find_function(src, "_onAlignment")
    assert "Request failed" not in api_body
    assert "That didn't go through (error" in api_body
    assert "Request failed" not in api_research_body
    assert "That didn't go through (error" in api_research_body
    assert "Request failed" not in alignment_body
    assert "That didn't go through (error" in alignment_body
    assert "I couldn't check that just now — try again in a moment." in alignment_body


def test_research_report_reasons_avoid_run_jargon():
    body = _find_function(_read(DIGEST_JS), "_onResearch")
    assert "I'm having trouble connecting right now. Try again shortly." in body
    assert "I couldn't run that research just now — try again in a moment." in body
    assert "The assistant is offline right now." not in body

    report_body = _find_function(_read(DIGEST_JS), "_showReport")
    assert "research brief" in report_body
    assert "reused a recent brief, so none were used" in report_body
    assert (
        "isn’t set up yet — connect it in Settings and I’ll "
        "be able to prepare briefs like this." in report_body
    )
    assert (
        "You’ve used all of this job search’s research briefs "
        "for now — they refresh over time." in report_body
    )
    assert "The research didn’t come together this time. Try again shortly." in report_body
    assert "Connect it in setup to enable research briefs." not in report_body
    assert "research run" not in report_body


def test_feedback_prompt_and_toasts_are_first_person():
    body = _find_function(_read(DIGEST_JS), "_onFeedback")
    assert "Tell me anything about my suggestions — what you'd like more or less of." in body
    assert "Nothing to send yet — write a quick note first." in body
    assert "I couldn't send that feedback just now — try again in a moment." in body
    assert "the assistant" not in body
    assert "Nothing to send.'" not in body


def test_survey_intro_and_hint_are_first_person():
    src = _read(DIGEST_JS)
    ask_survey_body = _find_function(src, "_askSurvey")
    assert "A few quick answers help me tune what I send." in ask_survey_body
    assert "help the assistant tune what it sends" not in ask_survey_body
    assert "the resume I prepared for these roles" in src
    assert "the resume the assistant prepared" not in src


def test_survey_submit_copy_fixes_grammar_and_voice():
    body = _find_function(_read(DIGEST_JS), "_onSurvey")
    assert "Pick at least one answer, or use “Send feedback” to write a note instead." in body
    assert "waiting for your OK on your to-do list" in body
    assert "need${pending === 1 ? 's' : ''} your OK in your to-do list" not in body
    assert "Thanks — that helps me tune what I send." in body
    assert "that helps the assistant tune things" not in body
    assert "I couldn't send the survey just now — try again in a moment." in body


def test_load_digest_offline_message_is_first_person():
    body = _find_function(_read(DIGEST_JS), "_loadDigest")
    assert "I'm having trouble connecting right now. Try again shortly." in body
    assert "I couldn't load today's updates just now — try again in a moment." in body
    assert "The assistant is offline right now." not in body


# ── node syntax check on both touched files ─────────────────────────────
#
# NOTE: this repo's established convention elsewhere (e.g.
# test_applicant_help_selfexplain_12.py) shells out to
# `node --check <path>`. That invocation form was found, while building this
# file, to give a FALSE PASS (exit 0) on these two ES modules even with a
# deliberately-broken, unterminated string literal injected — verified by
# hand against a scratch copy. The reliable form in this Node version
# (v22.x) is `node --input-type=module --check` fed the source over stdin,
# which correctly fails on the same deliberately-broken copy. Use that form
# here so this test actually gates syntax the way it's meant to.
def test_node_check_touched_files_via_stdin_module_mode():
    if shutil.which("node") is None:
        import pytest
        pytest.skip("node binary not on PATH")
    for path in (DOCLIB_JS, DIGEST_JS):
        res = subprocess.run(
            ["node", "--input-type=module", "--check"],
            input=_read(path),
            capture_output=True, text=True, timeout=30,
        )
        assert res.returncode == 0, (
            f"node --input-type=module --check failed for {path.name}:\n{res.stderr}"
        )
