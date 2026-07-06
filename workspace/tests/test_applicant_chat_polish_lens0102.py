"""Regression coverage for the copy & voice (exhaustive2, lens 02) and
micro-interactions (exhaustive2, lens 01) audit findings applied to
``workspace/static/js/applicantChat.js`` in this pass.

Almost every numbered finding tied to this file in
``docs/design/audits/exhaustive2/02_copy_voice.md`` (#187, #201-204, #232) and
``docs/design/audits/exhaustive2/01_micro_interactions.md`` (#2, #3, #14, #15,
#49, #56, #79, #80, #84, #93) was already applied on HEAD by prior passes —
the busy/disabled send guard, the isComposing IME guards, the "advertise the
chord" resolution of Enter-vs-Ctrl+Enter, the composer-clear-only-on-success
fix, the no-duplicate-bubble retry, the conversation-persists-across-reopens
fix, the stale-render `seq` guard on the thread intro, the real gated CTA
button, and the starter prompts hiding after the first send were all already
present. This pass closes the two gaps still outstanding on this file:

- Lens 01 #28: the composer was a fixed ``rows="2"`` box with manual
  ``resize:vertical`` only, so a multi-line question scrolled inside a
  two-line window. It now auto-grows with typed content (capped at ~6 rows)
  via a shared ``_autoGrowComposer`` helper wired to input/prefill/clear.
- Lens 02 cross-cutting #2 ("raw e.message shown to users as toast copy") and
  #3 (curly vs straight apostrophes): three ``_toast(e.message || …)`` call
  sites still surfaced raw proxy/engine internals instead of routing through
  the shared ``errText()`` helper, and two user-facing strings (the chat
  guardrail hint and the thread-intro greeting) still used a straight
  apostrophe instead of the house style's curly one. The starter-prompt chip
  "Tell me what you're looking for" is deliberately left with its straight
  apostrophe: ``test_applicant_chat_help_prompt_lens12.py`` asserts that
  exact string verbatim (lens 12, finding #46), and that test file is out of
  this lane's single-file scope to update.

Every assertion here was verified, by hand, to go red when the underlying
fix is reverted (a `cp` backup to /tmp, revert the file, rerun, confirm the
assertion fails, then restore) — the backup itself is not committed.
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
    the agent's own voice. Three call sites in this file still did
    ``_toast(e.message || '...')`` directly; they must route through the
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
    remain anywhere in the file after this pass."""
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
    """Guard against regressing findings a prior pass already landed on this
    file (first-person gated state #201, non-restating send tooltip #202,
    "search" terminology #203, grammar-correct pending-count string #187, and
    the plain-language "no reply" fallback #232)."""
    js = _read()
    assert "Connect a model in Settings and I can answer questions about your " in js
    assert 'title="Send — or press Ctrl+Enter"' in js
    assert "<strong>Search update</strong>" in js
    assert "Proposed search update" in js
    assert "_toast('Search settings updated');" in js
    assert (
        "item${count === 1 ? '' : 's'} need${count === 1 ? 's' : ''} your attention"
        in js
    )
    assert "I didn't get a reply — please try sending that again." in js


# ── micro-interactions (lens 01) ────────────────────────────────────────────


def test_composer_auto_grows_instead_of_manual_resize_only():
    """#28: the composer used to be ``rows="2"`` with ``resize:vertical`` and
    nothing else — a three-line question scrolled inside a two-line box.
    There must now be a shared auto-grow helper wired to the input event
    (and to prefill / post-send clear), and the inline manual-resize style
    must be gone."""
    js = _read()
    assert "function _autoGrowComposer(input)" in js
    assert "resize:vertical" not in js
    assert "resize:none" in js
    # Wired on typing, on starter-prompt prefill, and after a successful send
    # clears the composer — not just rendered once and forgotten.
    assert "input.addEventListener('input', () => _autoGrowComposer(input));" in js
    assert "_autoGrowComposer(input);" in js  # appears at least once beyond the def


def test_isComposing_ime_guards_present_on_both_enter_handlers():
    """#15: an IME composition-commit Enter (CJK / dead-key input) must not
    fall through to the create-job-search action or the send chord."""
    js = _read()
    assert "if (e.key === 'Enter' && !e.isComposing && e.keyCode !== 229) create();" in js
    assert "if (e.isComposing || e.keyCode === 229) return;" in js


def test_send_button_busy_disabled_guard_during_in_flight_request():
    """The send button must be disabled and show a busy label while a
    message request is in flight, and restored afterward — the guard this
    lane's micro-interaction typical-pattern calls out explicitly."""
    js = _read()
    assert "sendBtn.disabled = true; sendBtn.textContent = '…';" in js
    assert "sendBtn.disabled = false; sendBtn.textContent = 'Send';" in js
    assert "_sending = true;" in js
    assert "_sending = false;" in js


def test_composer_clears_only_after_success_and_not_on_failure():
    """Lens 01 #2 (already fixed on HEAD, guarded here against regression):
    on failure the typed text must survive so the user isn't forced to
    retype; it is only cleared once the POST actually resolves."""
    js = _read()
    assert (
        "if (input && input.value === message) { input.value = ''; _autoGrowComposer(input); }"
        in js
    )


def test_retry_does_not_duplicate_the_user_bubble():
    """Lens 01 #3 (already fixed on HEAD, guarded here against regression):
    Retry must resend against the SAME bubble via `_sendToBubble`, never by
    calling `_send` (which would re-append a user bubble)."""
    js = _read()
    assert "_sendToBubble(message, thinking);" in js
    assert "retry.addEventListener('click', () => {" in js


def test_autoscroll_on_new_message_present():
    """Every appended message bubble must scroll itself into view so new
    turns are visible without a manual scroll."""
    js = _read()
    assert "wrap.scrollIntoView({ block: 'nearest' });" in js


def test_focus_returns_to_composer_after_send_and_after_reopen():
    """Focus must return to the composer once a send request settles, and
    again when reopening an already-live conversation."""
    js = _read()
    assert "if (input) input.focus();" in js
    # The reopen short-circuit (#49) also refocuses the composer.
    assert "if (input) input.focus();\n    return;" in js


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
