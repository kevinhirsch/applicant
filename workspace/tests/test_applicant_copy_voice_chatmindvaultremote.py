"""Regression coverage for the copy & voice (exhaustive2, lens 02) audit
findings implemented on the Chat/Mind/Vault/Remote front-door surfaces only
(``static/js/applicantChat.js``, ``static/js/applicantMind.js``,
``static/js/applicantVault.js``, ``static/js/applicantRemote.js``).

House voice per ``docs/design/audits/exhaustive2/02_copy_voice.md``:
first-person-singular ("I"), calm, plain, quietly confident — never
third-person self-reference ("the assistant", "it"), never engineering
vocabulary ("criteria", "sandbox", "stop-boundary", "session" for the
takeover surface, "tenant"), no raw plural hacks ("role(s)"), curly
apostrophes in new copy.

Follows the convention of ``test_applicant_a11y_micro_chatmindvaultremote.py``:
every fact is read from the actual static file content via ``pathlib`` +
regex/substring — no browser, no DOM, no real socket. Each assertion here
was verified, by hand, to go red when the underlying fix is reverted
(revert the file -> rerun -> see the assertion fail -> restore) per the
batch's test-coverage DoD; the file-copy backups used for that are NOT
committed (only the source fixes + this test file are).

Findings from the audit that were judged NOT applicable to these four files
(out of hard scope, or the underlying string doesn't actually live where the
audit line number suggests) are intentionally not covered here; see the
session report for the full list of deferrals.
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
JS_DIR = REPO_ROOT / "workspace" / "static" / "js"
CHAT_JS = JS_DIR / "applicantChat.js"
MIND_JS = JS_DIR / "applicantMind.js"
VAULT_JS = JS_DIR / "applicantVault.js"
REMOTE_JS = JS_DIR / "applicantRemote.js"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# ── Chat (applicantChat.js) ─────────────────────────────────────────────────


def test_chat_pending_count_grammar_agrees_for_singular_and_plural():
    """#187: the pending-count sentence used to always say "need" even for a
    single item ("1 item need your attention") — a bare grammar bug."""
    js = _read(CHAT_JS)
    assert "need${count === 1 ? 's' : ''} your attention" in js
    assert "need your attention</strong>" not in js


def test_chat_gated_state_speaks_in_first_person():
    """#201: the not-connected gate used to third-person the Job Assistant
    ("Once a model is connected it can answer questions...")."""
    js = _read(CHAT_JS)
    assert "Once a model is" not in js
    assert "connected it can answer questions and surface" not in js
    assert "Connect a model in Settings and I can answer questions about your" in js
    assert "flag anything that needs your input" in js


def test_chat_send_button_tooltip_is_not_third_person_restatement():
    """#202: the Send tooltip used to say "Send to the assistant" — third
    person and a bare restatement of the visible "Send" label."""
    js = _read(CHAT_JS)
    assert "Send to the assistant" not in js
    assert 'title="Send — or press Ctrl+Enter"' in js


def test_chat_criteria_jargon_renamed_to_search_update():
    """#203: "Criteria" is CRM/engineering vocabulary; the chat surface's
    criteria-refocus card and its confirm toast must say "search" instead,
    matching the rest of the front door."""
    js = _read(CHAT_JS)
    assert "<strong>Criteria change</strong>" not in js
    assert "<strong>Search update</strong>" in js
    assert "Proposed criteria update" not in js
    assert "Proposed search update" in js
    assert "_toast('Criteria updated')" not in js
    assert "_toast('Search settings updated')" in js
    assert "Could not save criteria change" not in js
    assert "Could not save the search update" in js


def test_chat_starter_prompt_drops_criteria_jargon():
    """#204: the tappable starter prompt said "Change my criteria"."""
    js = _read(CHAT_JS)
    assert "'Change my criteria'" not in js
    assert "'Change what you look for'" in js


def test_chat_no_reply_fallback_is_not_a_bare_parenthetical():
    """#232: a missing engine reply rendered the bare, systemy "(no reply)"."""
    js = _read(CHAT_JS)
    assert "'(no reply)'" not in js
    assert "I didn't get a reply — please try sending that again." in js


# ── Mind (applicantMind.js) ──────────────────────────────────────────────────


def test_mind_dialog_title_is_first_person():
    """#142: the Mind dialog's own title and its Brain-modal launcher button
    both said "What the assistant remembers" — third person on a surface
    that elsewhere already speaks as "I" (e.g. "How I check it worked").
    (Dev comments describing the pre-fix history are expected to still
    mention the old phrase — only the two actual user-facing strings must
    have changed.)"""
    js = _read(MIND_JS)
    m = re.search(r'<h3 id="applicant-mind-title"[^>]*>([^<]*)</h3>', js)
    assert m and m.group(1) == "What I remember"
    assert "btn.textContent = 'What I remember';" in js
    assert "btn.textContent = 'What the assistant remembers';" not in js


def test_mind_offline_note_is_first_person_no_ai_model_jargon():
    """#163: the not-connected note said "Connect an AI model..." and
    "what the assistant remembers" — third person plus internal jargon
    ("AI model" is used nowhere else; everywhere else it's just "a model")."""
    js = _read(MIND_JS)
    assert "Connect an AI model to start building what the assistant remembers" not in js
    assert "Connect a model in Settings or the setup wizard, and I'll start remembering" in js
    assert "what I learn." in js


def test_mind_playbooks_empty_state_is_first_person():
    """#164: the empty saved-playbooks note said "The assistant writes
    these from its own work.\""""
    js = _read(MIND_JS)
    assert "No saved playbooks yet. The assistant writes these from its own work." not in js
    assert "No saved playbooks yet. I write these as I learn from my own work." in js


def test_mind_forget_button_tooltip_is_first_person():
    """#165: the per-note Forget button's tooltip said "Ask the assistant
    to forget this\""""
    js = _read(MIND_JS)
    assert "Ask the assistant to forget this" not in js
    assert 'title="I\'ll forget this note"' in js


def test_mind_forget_confirm_states_the_consequence():
    """#166: the forget confirm dialog asked the question but never said
    what forgetting actually does."""
    js = _read(MIND_JS)
    assert "`Forget this note?\\n\\n${text}`" not in js
    assert "Forget this note? I'll stop using it and it won't come back." in js


def test_mind_toasts_drop_trailing_periods_to_match_portal_convention():
    """#170: Mind's toasts ("Saved.", "Dismissed.", "Forgotten.") carried a
    trailing period the rest of the front door (e.g. Portal's "Sent",
    "Marked as handled") does not."""
    js = _read(MIND_JS)
    assert "_toast('Saved.')" not in js
    assert "_toast('Dismissed.')" not in js
    assert "_toast('Forgotten.')" not in js
    assert "_toast('Saved')" in js
    assert "_toast('Dismissed')" in js
    assert "_toast('Forgotten')" in js


def test_mind_close_button_tooltip_no_longer_restates_its_own_label():
    """#173: the Close button carried a title="Close" tooltip that just
    repeated its own visible text — the aria-label stays for AT, the
    redundant visible tooltip is dropped."""
    js = _read(MIND_JS)
    assert 'class="cal-btn applicant-mind-close" aria-label="Close" title="Close"' not in js
    assert 'class="cal-btn applicant-mind-close" aria-label="Close">Close' in js


def test_mind_authority_claim_warning_is_plain_language_not_legalese():
    """#176: the "claims authority" flag on a curated note used stiff
    legalese ("grants no permission") instead of plain, first-person
    reassurance."""
    js = _read(MIND_JS)
    assert "it is a suggestion only and" not in js
    assert "grants no permission" not in js
    assert "It's only a suggestion — I won't do" in js
    assert "anything without your say-so" in js


# ── Vault (applicantVault.js) ────────────────────────────────────────────────


def test_vault_intro_paragraph_is_first_person():
    """#182: the vault's own intro paragraph said "so the assistant can
    sign in for you" on the passwords surface."""
    js = _read(VAULT_JS)
    assert "so the assistant can sign in for you" not in js
    assert "Save the username and password for a job site so I can sign in for you." in js


def test_vault_site_field_tooltip_drops_tenant_jargon():
    """#183: the per-site field's tooltip said "tenant" — internal
    multi-tenancy vocabulary with no meaning to an end user."""
    js = _read(VAULT_JS)
    assert "The job site or employer tenant this sign-in is for" not in js
    assert "The job site or employer this sign-in is for" in js


def test_vault_capture_confirm_is_first_person_with_curly_quotes_and_not_now():
    """#199: the live-takeover capture-offer confirm was third person, used
    straight quotes, and its decline label ("No thanks") diverged from the
    Remote surface's equivalent offer ("Not now")."""
    js = _read(VAULT_JS)
    assert 'so the assistant can ' not in js
    assert '`Save the sign-in you just used for “${c.tenantKey}” so I can `' in js
    assert "Your password is encrypted and never shown again." in js
    assert "cancelText: 'No thanks'" not in js
    assert "cancelText: 'Not now'" in js


def test_vault_google_signin_description_is_first_person():
    """#200: the account-level Google sign-in description said "lets the
    assistant use..." — third person on the sensitive-credentials surface."""
    js = _read(VAULT_JS)
    assert "lets the assistant use" not in js
    assert "lets me use “Sign in with Google” on any site" in js


def test_vault_site_specific_heading_reads_as_a_sentence():
    """#227: the per-site-sign-in card heading read "A specific site
    sign-in" — awkward noun-pile phrasing."""
    js = _read(VAULT_JS)
    assert "A specific site sign-in" not in js
    assert "Sign-in for a specific site" in js


def test_vault_refresh_tooltip_states_what_it_reloads():
    """#228: the Refresh button's tooltip was the bare, restating "Reload"."""
    js = _read(VAULT_JS)
    assert 'title="Reload">Refresh</button>' not in js
    assert 'title="Reload the list of saved sign-ins">Refresh</button>' in js


# ── Remote (applicantRemote.js) ──────────────────────────────────────────────


def test_remote_snapshot_empty_state_drops_stop_boundary_jargon():
    """#177: the pre-submit snapshot's empty state used the internal spec
    term "stop-boundary" in user-facing copy."""
    js = _read(REMOTE_JS)
    assert "at the stop-boundary" not in js
    assert "I've filled everything in and stopped before the final submit" in js


def test_remote_authorize_confirm_message_is_first_person():
    """#178: the irreversible authorize-confirm message said "Authorize the
    assistant to click the final submit..." at the highest-gravity moment
    in the product."""
    js = _read(REMOTE_JS)
    assert "Authorize the assistant to click the final submit for" not in js
    assert "Let me click the final submit for ${who}, just this once?" in js
    # The "materials approved" consequence line must survive untouched.
    assert "Materials approved ✓ — this submits immediately and cannot be undone." in js


def test_remote_authorize_button_pairs_with_submit_it_myself_voice():
    """#179: "Authorize the assistant to finish" broke the decision pair's
    voice against its sibling "I'll submit it myself"."""
    js = _read(REMOTE_JS)
    assert "Authorize the assistant to finish" not in js
    assert 'title="I\'ll click the final submit — only after you confirm here">Submit it for me</button>' in js


def test_remote_live_session_intro_is_first_person():
    """#180: the flagship live-takeover intro paragraph said "Watch the
    assistant fill out your application..."."""
    js = _read(REMOTE_JS)
    assert "Watch the assistant fill out your application" not in js
    assert "Watch me fill out your application in real time. Take over at any" in js


def test_remote_desktop_help_note_says_computer_not_sandbox():
    """#181 (+ #223 apostrophe-style dup): both the static markup default and
    the JS-rendered note said "isn't set up on this sandbox yet" — "sandbox"
    is internal infra vocabulary, and the two copies mixed straight/curly
    apostrophes."""
    js = _read(REMOTE_JS)
    assert "on this sandbox yet" not in js
    assert js.count("desktop help isn’t set up on this computer yet") == 2


def test_remote_authorize_success_toast_is_first_person():
    """#191: the post-authorize toast credited "the assistant"."""
    js = _read(REMOTE_JS)
    assert "Authorized — the assistant submitted the application" not in js
    assert "Done — I submitted the application for you" in js


def test_remote_stop_boundary_footnote_is_first_person():
    """#192: the reassurance line under the decision pair said "The
    assistant can only click the final submit... it never submits..."."""
    js = _read(REMOTE_JS)
    assert "The assistant can only click the final submit" not in js
    assert "I can only click the final submit when you authorize it" in js
    assert "I never submit on my own." in js


def test_remote_finish_card_intro_is_first_person():
    """#193: the "Finish the application" card intro said "The assistant
    has pre-filled everything and stopped..."."""
    js = _read(REMOTE_JS)
    assert "The assistant has pre-filled everything and stopped" not in js
    assert "I've filled in everything and stopped before the final" in js


def test_remote_desktop_help_card_heading_and_tooltip_are_first_person():
    """#194: the desktop-help card heading ("Let the assistant help on the
    desktop") and its Turn-on tooltip both third-personed the agent. (A dev
    comment describing the feature's history is expected to still mention
    the old phrase — only the two rendered user-facing strings must have
    changed.)"""
    js = _read(REMOTE_JS)
    assert ">Let me help on the desktop</h5>" in js
    assert "flex:1 1 auto;\">Let the assistant help on the desktop</h5>" not in js
    assert "Let the assistant handle desktop steps the browser can't reach" not in js
    assert "Let me handle desktop steps the browser can't reach" in js


def test_remote_desktop_help_body_is_first_person():
    """#195: the desktop-help description said "it never creates accounts,
    clears verifications, or submits, and it asks before each step."""
    js = _read(REMOTE_JS)
    assert "it never creates accounts,\n            clears verifications, or submits, and it asks" not in js
    assert "I never create accounts,\n            clear verifications, or submit, and I ask before each step." in js


def test_remote_desktop_help_status_notes_are_first_person():
    """#196: the on/off status notes under the desktop-help toggle said
    "The assistant asks..." / "...let the assistant help..."."""
    js = _read(REMOTE_JS)
    assert "The assistant asks before each desktop step and never submits on its own." not in js
    assert "Off. Turn it on to let the assistant help with desktop steps" not in js
    assert "On for this session. I'll ask before each desktop step and never submit on my own." in js
    assert "Off. Turn it on and I'll help with desktop steps for this session only." in js


def test_remote_resume_controls_card_is_first_person():
    """#197: "Use these once you have finished a step the assistant can't
    do on its own.\""""
    js = _read(REMOTE_JS)
    assert "the assistant can't do on its own" not in js
    assert "Use these once you've finished a step I can't do on my own." in js


def test_remote_offer_save_signin_confirm_is_first_person():
    """#198: the post-resume-account offer to save credentials said "so the
    assistant can reuse it next time"."""
    js = _read(REMOTE_JS)
    assert "so the assistant can reuse it next" not in js
    assert "so I can reuse it next " in js


def test_remote_snapshot_load_failure_is_plain_language_first_person():
    """#208: the snapshot-preview load failure said "Can't reach the
    assistant to load the snapshot right now." — third person plus
    "snapshot" jargon."""
    js = _read(REMOTE_JS)
    assert "Can’t reach the assistant to load the snapshot right now." not in js
    assert "I can't load what will be sent right now — try again in a moment." in js


def test_remote_refresh_sessions_button_drops_session_jargon():
    """#225: the toolbar button read "Refresh sessions" — "session" is
    engineering vocabulary; the tooltip already says what it reloads."""
    js = _read(REMOTE_JS)
    assert ">Refresh sessions</button>" not in js
    assert ">Refresh list</button>" in js


def test_remote_snapshot_preview_caption_drops_immutable_jargon():
    """#226: the "what will be sent" preview caption used "immutable" —
    engineering vocabulary for "won't change"."""
    js = _read(REMOTE_JS)
    assert "The immutable record for this application" not in js
    assert "The exact, unchangeable record for this application" in js


def test_remote_empty_live_view_offers_orientation():
    """#239: the empty live-view overlay said only "No live session is open
    yet." with no orientation for what will appear or when."""
    js = _read(REMOTE_JS)
    m = re.search(r'<div id="applicant-remote-empty"[^>]*>\s*([^<]*)\s*</div>', js)
    assert m, "expected the empty live-view overlay markup"
    assert m.group(1).strip() == "No live session is open yet — when I'm working in a browser, it appears here."


# ── brace-balance sanity (all four files) ───────────────────────────────────


def _balanced_braces(js: str) -> bool:
    return js.count("{") == js.count("}")


def test_all_four_files_stay_brace_balanced_after_copy_pass():
    for path in (CHAT_JS, MIND_JS, VAULT_JS, REMOTE_JS):
        js = _read(path)
        assert _balanced_braces(js), f"{path.name} has unbalanced braces"
