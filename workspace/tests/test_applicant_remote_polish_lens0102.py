"""Regression coverage for the remaining copy & voice (exhaustive2, lens 02)
and micro-interactions (exhaustive2, lens 01) audit findings applied to
``workspace/static/js/applicantRemote.js`` in this pass.

Most of the numbered findings for this file (177-239 in
``docs/design/audits/exhaustive2/02_copy_voice.md`` and #7/#35/#37/#78/#86/#87
in ``docs/design/audits/exhaustive2/01_micro_interactions.md``) were already
applied on HEAD (see ``test_applicant_copy_voice_chatmindvaultremote.py`` and
``test_applicant_a11y_micro_chatmindvaultremote.py``, which cover them). This
file covers the handful of items that were still outstanding on this file
after that prior pass:

- The house voice's first-person rule ("I", never "the assistant") was not
  yet applied to the "fill these in yourself" emergency-handoff note (default
  markup + both ``_renderHandoff`` branches) — not tied to a specific numbered
  finding, but squarely inside the lens's cross-cutting pronoun rule.
- The "raw ``e.message`` shown as toast copy" cross-cutting rule (#2) had
  already been applied to the snapshot-preview error path (``errText(e)``)
  but six other ``_toast(e.message || …)`` call sites in this file still
  surfaced raw engine/proxy internals.
- Micro-interactions #55 (Escape can't close Remote once focus is inside the
  live iframe): the prior pass deferred this because the *kit*-level fix
  lives in ``ui.js`` (out of file scope). This pass adds the file-scoped half
  of the suggested fix — refocusing the shell when the pointer leaves the
  iframe, so Escape becomes reachable again without requiring a ui.js change.

Findings judged not applicable to a single-file lane and intentionally left
unfixed here (already documented as deferred in the prior pass's test file):
Remote's session-picker raw-UUID labels (#61, needs a backend payload change
outside this file) and the ``ui.js``-level focus-trap/dialog-kit fixes.

Every assertion here was verified, by hand, to go red when the underlying
fix is reverted (revert the file -> rerun -> see the assertion fail ->
restore); the file-copy backup used for that is not committed.
"""

from __future__ import annotations

import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
JS_DIR = REPO_ROOT / "workspace" / "static" / "js"
REMOTE_JS = JS_DIR / "applicantRemote.js"


def _read() -> str:
    return REMOTE_JS.read_text(encoding="utf-8")


# ── copy (lens 02) ───────────────────────────────────────────────────────────


def test_handoff_default_markup_note_is_first_person():
    """The static default text for the emergency-handoff note (overwritten
    at runtime by ``_renderHandoff`` but still real markup) used to say "The
    assistant couldn't fill this form automatically."."""
    js = _read()
    assert "The assistant couldn't fill this form automatically" not in js
    assert "I couldn't fill this form automatically. Copy each answer below" in js


def test_handoff_wrong_ats_note_is_first_person():
    """``_renderHandoff``'s wrong-ATS branch used to say "The assistant
    didn't recognize this form well enough...\""""
    js = _read()
    assert "The assistant didn’t recognize this form well enough" not in js
    assert "The assistant didn't recognize this form well enough" not in js
    assert "I didn’t recognize this form well enough to fill it in " in js


def test_handoff_generic_error_note_is_first_person():
    """``_renderHandoff``'s generic-error branch used to say "The assistant
    tried to fill this form and ran into a problem.\""""
    js = _read()
    assert "The assistant tried to fill this form and ran into a problem" not in js
    assert "I tried to fill this form and ran into a problem. Copy each " in js


def test_no_more_assistant_third_person_in_user_facing_handoff_strings():
    """Belt-and-suspenders: none of the three handoff-note variants (default
    markup + both _renderHandoff branches) should still say "The assistant"
    anywhere in this file's user-facing strings."""
    js = _read()
    assert "The assistant" not in js


def test_toast_error_paths_map_through_errtext_not_raw_e_message():
    """Cross-cutting finding #2: raw ``e.message`` surfaced as toast copy
    exposes proxy/engine internals (HTTP status text, JSON parse errors) as
    the agent's own voice. Six call sites in this file still did
    ``_toast(e.message || '...')`` directly; they must route through the
    calm, plain-language ``errText(e)`` helper (already imported from
    applicantCore.js and already used on the snapshot-preview error path)."""
    js = _read()
    assert "_toast(e.message || 'Could not change desktop help')" not in js
    assert "_toast(e.message || 'Could not load live sessions')" not in js
    assert "_toast(e.message || 'Could not take control')" not in js
    assert "_toast(e.message || 'Could not continue')" not in js
    assert "_toast(e.message || 'Could not record the submission')" not in js
    assert "_toast(e.message || 'Could not authorize the submission')" not in js

    assert "_toast(errText(e) || 'Could not change desktop help')" in js
    assert "_toast(errText(e) || 'Could not load live sessions')" in js
    assert "_toast(errText(e) || 'Could not take control')" in js
    assert "_toast(errText(e) || 'Could not continue')" in js
    assert "_toast(errText(e) || 'Could not record the submission')" in js
    assert "_toast(errText(e) || 'Could not authorize the submission')" in js


def test_no_raw_e_message_toasts_remain_anywhere_in_the_file():
    """Belt-and-suspenders sweep: no ``_toast(e.message`` call site should
    remain anywhere in the file after this pass."""
    js = _read()
    assert "_toast(e.message" not in js


def test_errtext_import_still_present_and_used_on_snapshot_path():
    """``errText`` must stay imported from applicantCore.js (it is the
    shared plain-language error mapper reused across the front door) and
    must still be used on the pre-existing snapshot-preview error path."""
    js = _read()
    assert "errText, loadingHTML, errorHTML, wireRetry," in js
    assert "errorHTML(errText(e))" in js


# ── micro-interactions (lens 01) ────────────────────────────────────────────


def test_iframe_mouseleave_refocuses_the_close_button():
    """#55: while focus sits inside the sandboxed live-session iframe,
    keydowns fire in the iframe's own document and never reach the modal's
    Escape handler. As soon as the pointer leaves the frame-wrap, focus must
    be handed back to the close button (a real, focusable, in-shell control)
    so Escape becomes reachable again without an explicit click."""
    js = _read()
    assert "frameWrap.addEventListener('mouseleave'" in js
    assert "document.activeElement === frame" in js
    assert "closeBtn.focus()" in js


def test_iframe_refocus_guard_only_fires_when_the_iframe_actually_had_focus():
    """The refocus must be conditional on the iframe currently holding
    focus — it must not unconditionally steal focus away from some other
    control the user is legitimately using elsewhere in the modal."""
    js = _read()
    assert "if (frame && closeBtn && document.activeElement === frame) closeBtn.focus();" in js


def test_finish_buttons_still_lock_after_a_successful_submit():
    """Guard against regressing the pre-existing #7 fix while touching
    nearby code in this pass: the decision-pair lock/terminal-state helpers
    must still be wired into both submit paths."""
    js = _read()
    assert "_markFinishTerminal('Submitted ✓ — thanks for finishing it yourself.')" in js
    assert "_markFinishTerminal('Submitted ✓ — I finished it for you.')" in js
    assert "function _clearFinishTerminal()" in js


def test_refresh_and_takeover_still_use_the_shared_busy_button_guard():
    """Guard against regressing the pre-existing #35/#37 fixes: refresh,
    takeover and resume must still route through the shared
    ``_setButtonBusy``/``_clearButtonBusy`` helpers."""
    js = _read()
    assert "_setButtonBusy(btn, 'Refreshing…')" in js
    assert "_setButtonBusy(btn, 'Taking control…')" in js
    assert "_setButtonBusy(btn, 'Continuing…')" in js


# ── sanity ───────────────────────────────────────────────────────────────────


def test_file_stays_brace_balanced_after_this_pass():
    js = _read()
    assert js.count("{") == js.count("}")
