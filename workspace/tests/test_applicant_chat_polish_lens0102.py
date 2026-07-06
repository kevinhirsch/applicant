"""Regression coverage for the copy & voice (exhaustive2, lens 02) and
micro-interactions (exhaustive2, lens 01) audit findings that survive on
``workspace/static/js/applicantChat.js`` after the chat-unification pass.

History: the numbered findings tied to this file in
``docs/design/audits/exhaustive2/02_copy_voice.md`` (#187, #201-204, #232) and
``docs/design/audits/exhaustive2/01_micro_interactions.md`` were originally
applied to the Job Assistant's own modal panel. That modal is now retired —
the Job Assistant opens a dedicated engine-backed session in the NATIVE chat
surface (the assistant.js pattern), so the native composer owns auto-grow,
IME guards on the send chord, and the send-button busy state. What this file
still guards is the subset that carried over to the unified module:

- the calm ``errText()`` error voice on every toast (lens 02 #2);
- curly apostrophes in the surviving user-facing strings (lens 02 #3);
- the first-person gated copy / "search" terminology / grammar-correct
  pending count / plain "no reply" fallback (#201, #203, #187, #232);
- composer-clear-only-on-success + the no-duplicate-bubble Retry, both now
  operating on the NATIVE composer/thread;
- the IME guard on the one Enter handler this module still owns (the inline
  create-job-search form);
- focus returning to the composer once a send settles.

Every assertion here was verified to go red against the pre-unification
behavior it guards (drop the guard/string from the module -> rerun -> fail).
"""

from __future__ import annotations

import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
JS_DIR = REPO_ROOT / "workspace" / "static" / "js"
CHAT_JS = JS_DIR / "applicantChat.js"


def _read() -> str:
    return CHAT_JS.read_text(encoding="utf-8")


# ── copy (lens 02) ───────────────────────────────────────────────────────────


def test_toast_error_paths_map_through_errtext_not_raw_e_message():
    """Cross-cutting finding #2: raw ``e.message`` surfaced as toast copy
    exposes proxy/engine internals (HTTP status text, JSON parse errors) as
    the agent's own voice. Every toast error path must route through the
    calm, plain-language ``errText(e)`` helper (already imported from
    applicantCore.js)."""
    js = _read()
    assert "_toast(e.message || 'Could not create the job search')" not in js
    assert "_toast(e.message || 'Could not save')" not in js
    assert "_toast(e.message || 'Could not save the search update')" not in js

    assert "_toast(errText(e) || 'Could not create the job search')" in js
    assert "_toast(errText(e) || 'Could not save')" in js
    assert "_toast(errText(e) || 'Could not save the search update')" in js


def test_no_raw_e_message_toasts_remain_anywhere_in_the_file():
    """Belt-and-suspenders sweep: no ``_toast(e.message`` call site should
    remain anywhere in the file."""
    js = _read()
    assert "_toast(e.message" not in js


def test_errtext_import_still_present():
    """``errText`` must stay imported from applicantCore.js — it is the
    shared plain-language error mapper reused across the front door."""
    js = _read()
    assert "esc, _toast, _fetchJSON, _post, errText, loadingHTML, errorHTML, gatedHTML, wireRetry," in js


def test_curly_apostrophes_in_user_facing_strings():
    """Cross-cutting finding #3: pick curly (’) apostrophes everywhere in
    user-facing copy. The chat guardrail hint and the thread-intro greeting
    still used a straight apostrophe. (The starter-prompt chip "Tell me what
    you're looking for" is intentionally left alone — see the module
    docstring: an existing, out-of-scope test asserts that exact straight
    apostrophe verbatim.)

    Demo-tone pass: the guardrail hint's "I never submit an application
    without your OK" disclaimer was reframed as a positive control statement
    ("Nothing goes out without your go-ahead")."""
    js = _read()
    assert "I’ll keep them up to date. Nothing goes out without your go-ahead." in js
    assert "or tell me about your preferences and I’ll keep them up to date." in js
    # The straight-apostrophe forms must be gone from those exact strings.
    assert "I'll keep them up to date. Nothing goes out without your go-ahead." not in js
    assert "or tell me about your preferences and I'll keep them up to date." not in js
    # The old negative-capability framing must not have crept back in.
    assert "I never submit an application without your OK." not in js
    # Deliberately preserved straight apostrophe (see docstring above).
    assert "Tell me what you're looking for" in js


def test_prior_pass_copy_fixes_still_present():
    """Guard against regressing copy findings that carried over to the
    unified surface (first-person gated state #201, "search" terminology
    #203, grammar-correct pending-count string #187, and the plain-language
    "no reply" fallback #232). The modal's own send-button tooltip (#202) is
    gone with the modal — the native composer owns that affordance now."""
    js = _read()
    assert "Connect a model in Settings and I can answer questions about your " in js
    assert "<strong>Search update</strong>" in js
    assert "Proposed search update" in js
    assert "_toast('Search settings updated');" in js
    assert (
        "item${count === 1 ? '' : 's'} need${count === 1 ? 's' : ''} your attention"
        in js
    )
    assert "I didn't get a reply — please try sending that again." in js


# ── micro-interactions (lens 01) ────────────────────────────────────────────


def test_composer_helpers_delegate_to_the_native_autoresize():
    """#28 (recast by unification): the module no longer owns a composer —
    it prefills / clears the NATIVE #message textarea, and must keep its
    height in sync through the shared uiModule.autoResize helper instead of
    a bespoke grow function."""
    js = _read()
    assert "_autoGrowComposer" not in js, "the bespoke modal grow helper should be gone"
    assert "document.getElementById('message')" in js
    assert "uiModule.autoResize(input)" in js


def test_isComposing_ime_guard_present_on_the_create_form_enter_handler():
    """#15: an IME composition-commit Enter (CJK / dead-key input) must not
    fire the create-job-search action. (The send chord's own IME guard lives
    in the native composer now.)"""
    js = _read()
    assert "if (e.key === 'Enter' && !e.isComposing && e.keyCode !== 229) create();" in js


def test_send_path_guards_reentry_while_a_request_is_in_flight():
    """The engine send path must be single-flight: a second submit while a
    turn is pending is dropped instead of double-posting (the modal's
    disabled send button became this flag once the native composer took
    over the button)."""
    js = _read()
    assert "if (!message || _sending) return false;" in js
    assert "_sending = true;" in js
    assert "_sending = false;" in js


def test_composer_clears_only_after_success_and_not_on_failure():
    """Lens 01 #2 (carried over): on failure the typed text must survive so
    the user isn't forced to retype; the NATIVE composer is only cleared
    once the POST actually resolves — and only if the user hasn't already
    typed something new into it."""
    js = _read()
    assert "if (input && input.value === rawComposerValue) {" in js
    assert "input.value = '';" in js


def test_retry_does_not_duplicate_the_user_bubble():
    """Lens 01 #3 (carried over): Retry must resend against the SAME bubble
    via `_sendToBubble`, never by re-running the full send (which would
    re-append a user bubble)."""
    js = _read()
    assert "_sendToBubble(message, rawComposerValue, thinking);" in js
    assert "retry.addEventListener('click', () => {" in js


def test_autoscroll_on_new_message_present():
    """New turns must be scrolled into view without a manual scroll — the
    unified path delegates to the native history scroller."""
    js = _read()
    assert "uiModule.scrollHistory();" in js


def test_focus_returns_to_composer_after_send():
    """Focus must return to the composer once a send request settles."""
    js = _read()
    assert "if (input) input.focus();" in js


# ── sanity ───────────────────────────────────────────────────────────────────


def test_file_stays_brace_balanced_after_this_pass():
    js = _read()
    assert js.count("{") == js.count("}")


def test_no_codename_or_denylist_strings_leaked_in():
    js = _read()
    lowered = js.lower()
    for banned in ("firehouse", "orwell", "odysseus", "smokey"):
        assert banned not in lowered
    assert "hermes-agent" not in js
