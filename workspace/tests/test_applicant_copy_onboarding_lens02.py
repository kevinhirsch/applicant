"""Regression coverage for the copy & voice audit
(``docs/design/audits/exhaustive2/02_copy_voice.md``), lens 02, confined to
the OOBE wizard / Settings renderers: ``applicantOnboarding.js``.

This is a copy-only pass: plain-language strings, one house voice
(first-person-singular, calm, no engineering vocabulary, no third-person
self-reference), consistent terminology (e.g. "browser" not "sandbox", one
spelling of "résumé" at the two sites the audit cites), and warmer
error/status copy. No DOM/logic changes — see the git history for the paired
source commit.

One audit item (#51's Welcome step-desc) is DELIBERATELY left in its original
third-person wording: the string is duplicated verbatim into
``static/js/models.js``'s welcome card (outside this pass's file-ownership
boundary) and is guarded by an existing drift test
(``test_applicant_round1_remainder_welcomecard.py``) that does an
exact-substring match against this file's source. Rewriting it here without
updating that sibling file in lockstep would silently break that guard, so
it's tracked as a follow-up rather than changed in this pass.

The other item (#36's ``NEVER_DOES`` list) WAS addressed, in a later
demo-tone pass: the list was reframed from "never"/negative-capability
phrasing to positive control statements, in lockstep with
``static/landing.html``'s ``#trust`` section
(``test_applicant_activation_funnel_09.py``). The wizard welcome step no
longer renders that list at all — it shows a single positive line
(``trustLine``) instead — so this file's own welcome-step assertions below
were updated to match.

Follows the established convention: every fact is read from the actual
static file content via ``pathlib`` — no browser, no DOM, no real socket.
Each assertion here was verified, by hand, to go red when the underlying fix
is reverted (temporarily restored the pre-fix source from a file-copy
backup, reran, saw a real ``AssertionError``, then restored from the backup
— never ``git stash``) before this file was landed.
"""

from __future__ import annotations

import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
JS_DIR = REPO_ROOT / "workspace" / "static" / "js"
ONBOARDING_JS = JS_DIR / "applicantOnboarding.js"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# ── Welcome step: still-first-person hairline + trust-list heading ─────────


def test_welcome_hairline_and_trust_heading_are_first_person():
    js = _read(ONBOARDING_JS)
    assert "skip it and tell me in chat" in js
    assert "tell Applicant in chat" not in js
    assert "where I browse live in Settings any time" in js
    # Demo-tone pass: the collapsed "What I never do" disclosure was replaced
    # with a single positive control statement — no <summary> disclosure left.
    assert "<summary>What I never do</summary>" not in js
    assert "<summary>What Applicant never does</summary>" not in js
    assert "ao-welcome-trust" in js


# ── Connect a model / LLM save error ────────────────────────────────────────


def test_connect_a_model_tooltip_and_save_error_are_first_person():
    js = _read(ONBOARDING_JS)
    assert "I use an AI model to read job posts and write your materials." in js
    assert "Applicant uses an AI model to read job posts" not in js
    assert "I couldn’t connect to this model: ${gateErr.message" in js
    assert "application engine" not in js


# ── Notifications step (channels, quiet hours, deliver-now, reminder) ──────


def test_notifications_step_is_first_person():
    js = _read(ONBOARDING_JS)
    assert "How I reach you — Discord and/or email" in js
    assert "so I can send you updates and ask for approvals" in js
    assert "How Applicant reaches you" not in js
    assert "so Applicant can send you updates" not in js
    assert ">Send yourself a test</h2>" in js
    assert "so I never ping you overnight" in js
    assert "Applicant holds approval requests" not in js
    assert "Need something that’s being held right now? I’ll release everything" in js
    assert "Want what is being held right now?" not in js
    assert "How long I wait before also emailing you about an approval I haven’t heard back on" in js
    assert "If an approval still needs you after this long, I also email you as a backstop." in js
    assert "Lower means I email sooner; higher means fewer emails." in js
    assert "Applicant waits before also emailing" not in js
    assert "Applicant also emails you as a backstop" not in js
    assert "Lower = emailed sooner" not in js
    assert "https://discord.com/api/webhooks/…" in js
    assert "https://discord.com/api/webhooks/..." not in js


def test_notifications_status_messages_drop_bare_failed_prefix():
    js = _read(ONBOARDING_JS)
    assert "Saving and sending…" in js
    assert "Saving + sending…" not in js
    assert '"That didn’t send: " + (e.message || "I couldn’t send that test.")' in js
    assert '"I couldn’t save that: " + (e.message || \'Try again shortly.\')' in js
    assert '"I couldn’t deliver those: " + (e.message || \'Try again shortly.\')' in js
    assert "Saved — I’ll email you after ${minutes} minutes." in js
    assert "Failed: " not in js


# ── Where I browse (automation step) + desktop help ─────────────────────────


def test_automation_step_drops_sandbox_jargon_for_browser():
    js = _read(ONBOARDING_JS)
    assert ">Where I browse " in js
    assert ">Automation sandbox " not in js
    assert "Most people keep the built-in browser." in js
    assert "Most people keep the built-in sandbox." not in js
    assert '<label class="settings-label">Runs in</label>' in js
    assert ">Built-in browser (recommended)</option>" in js
    assert ">Built-in sandbox (recommended)</option>" not in js
    assert "isn’t set up on this browser yet." in js
    assert "isn’t set up on this sandbox yet." not in js


def test_desktop_help_is_first_person_and_available_state_keeps_action_label():
    js = _read(ONBOARDING_JS)
    assert "Lets me handle steps outside the web page" in js
    assert "Lets the assistant handle steps that live outside the web page" not in js
    assert 'title="Let me help with desktop steps the browser can\'t reach"' in js
    assert "Let the assistant help with desktop steps the browser" not in js
    assert "I only help with desktop steps you" in js
    assert "The assistant only helps with desktop steps you" not in js
    # #49: the toggle must keep an action label ("Turn on") even once the
    # capability becomes available — not flip to a bare state word.
    assert "btn.textContent = 'Turn on';" in js
    assert "btn.textContent = 'Available';" not in js
    assert "Ready. Turn it on from the live browser window whenever you need it." in js
    assert "Ready. Turn it on for a session from the live-session window" not in js


def test_vm_id_label_unified_with_its_own_tooltip():
    js = _read(ONBOARDING_JS)
    assert ">VM ID " in js
    assert "The VM ID of your licensed Windows VM" in js
    assert "Add the Proxmox API URL, node, token id and the VM ID to continue." in js
    assert "Windows VM id" not in js


# ── Fonts step: résumé spelling ──────────────────────────────────────────────


def test_fonts_step_uses_resume_with_accent():
    js = _read(ONBOARDING_JS)
    assert "Check a résumé for required fonts" in js
    assert "Check a resume for required fonts" not in js


# ── Work authorization + EEO section ────────────────────────────────────────


def test_visa_sponsorship_label_has_the_missing_article():
    js = _read(ONBOARDING_JS)
    assert "Will you need visa sponsorship now or in the future?" in js
    assert "now or in future?" not in js


def test_eeo_desc_is_first_person_and_options_are_sentence_case():
    js = _read(ONBOARDING_JS)
    assert "— I never guess these." in js
    assert "— we never guess these." not in js
    assert "label: 'Decline to self-identify'" in js
    assert "label: 'Prefer to answer'" in js
    # The persisted value must stay the original lowercase string so
    # previously-saved answers still match on re-render.
    assert "value: 'decline to self-identify'" in js
    assert "value: 'prefer to answer'" in js


# ── Readiness banner ─────────────────────────────────────────────────────────


def test_readiness_banner_is_first_person():
    js = _read(ONBOARDING_JS)
    assert "I have what I need to start applying." in js
    assert "just tell me in chat — I’ll keep learning as you go." in js
    assert "Before I can start applying, I still need:" in js
    assert "Applicant has what it needs to start applying" not in js
    assert "tell Applicant in chat — it'll keep learning" not in js
    assert "Before it can start applying, Applicant still needs" not in js


# ── Base résumé step, conflicts, preview ─────────────────────────────────────


def test_base_resume_step_is_first_person_and_says_resume_with_accent():
    js = _read(ONBOARDING_JS)
    assert "Start with your résumé " in js
    assert "I read your résumé and fill in the rest of your profile" in js
    assert "upload your current résumé and I’ll read it to fill in the profile fields" in js
    assert "just tell me what you want in chat" in js
    assert "Applicant reads your resume and fills in the rest of your profile" not in js
    assert "we also build a high-fidelity version" not in js
    assert "just tell Applicant what you want in chat" not in js


def test_resume_parse_success_message_is_first_person():
    js = _read(ONBOARDING_JS)
    # HONESTY (live audit): the count is the engine's per-parse field count
    # (parsed_field_count), and the confident success line only renders for a
    # real, non-trivial parse — never the attribute-cloud total.
    assert "I read ${n} details from your résumé and filled in the next steps" in js
    assert "res.attribute_count" not in js
    assert "we’ve filled in the next steps" not in js


def test_conflict_resolver_is_first_person_with_clear_radio_labels():
    js = _read(ONBOARDING_JS)
    assert "A few details in your résumé differ from what you told me." in js
    assert "what you told us." not in js
    assert "Keep your answer: ${esc(c.interview_value)}" in js
    assert "Use the résumé's: ${esc(c.parsed_value)}" in js
    assert "Use resume: " not in js


def test_preview_card_says_polished_version_of_resume_with_accent():
    js = _read(ONBOARDING_JS)
    assert "I built a polished version of your résumé (" in js
    assert "We built a high-fidelity version of your resume" not in js


# ── Finish screen ────────────────────────────────────────────────────────────


def test_finish_screen_is_first_person_without_an_exclamation():
    js = _read(ONBOARDING_JS)
    assert "I’m ready to start applying for you." in js
    assert (
        "I’m set up. Before I start applying I still need: "
        "${esc(applyMissing.join(', '))} — tell me in chat or add a résumé "
        "any time, and I’ll begin on my own."
    ) in js
    assert "You’re all set.</h2>" in js
    assert "Applicant is ready to start applying for you." not in js
    assert "Applicant is set up. Before it starts applying" not in js
    assert "You’re all set!</h2>" not in js


# ── Update trigger ───────────────────────────────────────────────────────────


def test_update_trigger_status_text_is_warmer():
    js = _read(ONBOARDING_JS)
    assert "out.textContent = 'Updating…';" in js
    assert "You’re already up to date." in js
    assert "out.textContent = 'Working…';" not in js
    assert "'Nothing to do.'" not in js
