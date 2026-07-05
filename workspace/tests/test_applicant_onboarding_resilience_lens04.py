"""Regression coverage for docs/design/audits/exhaustive2/04_failure_paths.md
findings #29a, #52, #59 and #68, all confined to
``workspace/static/js/applicantOnboarding.js`` (the first-run setup wizard /
Settings-reused step renderers).

Follows the convention of ``test_applicant_chatstream_guard_lens04.py`` (itself
following ``test_applicant_backlog_dupguard.py``): every fact is read from the
actual static file content via ``pathlib`` + regex — no browser, no DOM, no
real socket.

Findings fixed:

* **#29a** — the conflict-apply (``#ao-conf-apply``) and résumé-conversion
  preview accept/reject (``#ao-prev-accept``/``#ao-prev-reject``) actions had
  no in-flight guard: a fast double-click replayed the whole confirm-conflict
  batch, or double-POSTed the accept/reject choice. Fixed with a local
  ``_setButtonBusy``/``_clearButtonBusy`` pair (mirroring the same-named,
  non-exported helpers in ``applicantRemote.js``) wired around each action.
* **#52** — the wizard (and the Settings panels that reuse its step renderers
  via ``mountSettingsStep``) had zero draft persistence: a reload or session
  expiry mid-section threw away everything typed. Fixed with a scoped
  sessionStorage draft (``_saveDraft``/``_restoreDraft``/``_clearDraft``),
  wired into ``_setBody`` (restore + wire-on-input) and cleared the moment a
  step's data is actually saved (``_advanceAndContinue`` /
  ``_nextIntakeOrComplete``) — explicitly excluding password-type fields and a
  denylist of credential-bearing text fields (Discord webhook, Apprise/SMTP
  URL, ntfy topic).
* **#59** — ``_buildPreview`` awaited the conversion-preview POST with no
  client deadline and no guard against overlapping calls (the resume-upload
  flow and the font-install "Continue" handler can both trigger a preview
  build back-to-back). Fixed with an explicit ``timeoutMs`` override and a
  module-level in-flight promise a second caller now attaches to instead of
  double-POSTing.
* **#68** — the conflict-apply handler read ``.value`` off a
  ``:checked`` query that null-derefed when a conflict radio was left
  unanswered. Fixed with an explicit null guard and a plain validation
  message instead of the generic "Could not apply choices" toast.

Each assertion below was verified failing by hand (temporarily reverting the
relevant fix from a backup of the pre-fix file, rerunning to see a real
``AssertionError``, then restoring the fix) before this file was landed.
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
ONBOARDING_JS = REPO_ROOT / "workspace" / "static" / "js" / "applicantOnboarding.js"


def _read() -> str:
    return ONBOARDING_JS.read_text(encoding="utf-8")


def _top_level_fn(src: str, name: str) -> str:
    """Extract a top-level (unindented) `function name(...) { ... }` body.

    Same convention as ``test_applicant_chatstream_guard_lens04.py``: the
    function's own closing brace is the first line consisting of a bare "}"
    with no leading whitespace. Also matches ``async function``.
    """
    m = re.search(rf"(?:async\s+)?function {re.escape(name)}\([^)]*\)\s*\{{(.*?)\n\}}", src, re.S)
    assert m, f"expected a top-level function {name}(...) in the source"
    return m.group(1)


# ── #29a / #68: conflict-apply in-flight guard + null-safe radio read ───────


def test_conflict_apply_has_an_in_flight_guard():
    body = _top_level_fn(_read(), "_renderConflicts")
    assert "applyBtn.disabled" in body, (
        "expected the conflict-apply handler to bail out early when the "
        "button is already disabled (in-flight guard)"
    )
    assert "_setButtonBusy(applyBtn" in body and "_clearButtonBusy(applyBtn" in body, (
        "expected _renderConflicts to use the busy-button helper pair around "
        "the Apply choices action"
    )


def test_conflict_apply_guards_the_unanswered_radio_null_deref():
    body = _top_level_fn(_read(), "_renderConflicts")
    # The old code read `.value` directly off the :checked query result. The
    # fix captures the element first and checks it before reading `.value`.
    assert re.search(r"querySelector\(`input\[name=\"ao-conf-\$\{i\}\"\]:checked`\)\s*;", body), (
        "expected the :checked lookup to be captured into a variable rather "
        "than chaining straight into .value"
    )
    assert re.search(r"if\s*\(!checkedEl\)", body), (
        "expected an explicit null guard on the captured :checked element "
        "before reading .value off it"
    )
    # Guard against regressing back to the bare chained read.
    assert 'input[name="ao-conf-${i}"]:checked`).value' not in body, (
        "must not chain .value directly off the :checked query result again"
    )


def test_conflict_apply_still_posts_the_chosen_value_per_conflict():
    """The guards must not change the actual save behavior."""
    body = _top_level_fn(_read(), "_renderConflicts")
    assert "/confirm-conflict" in body
    assert "choice === 'parsed' ? c.parsed_value : c.interview_value" in body


# ── #29a / #59: preview accept/reject in-flight guard + build deadline ──────


def test_preview_accept_reject_have_an_in_flight_guard():
    body = _top_level_fn(_read(), "_buildPreview")
    assert "acceptBtn.disabled" in body and "rejectBtn.disabled" in body, (
        "expected accept/reject click handlers to bail out when already disabled"
    )
    assert "_setButtonBusy(acceptBtn" in body and "_clearButtonBusy(acceptBtn" in body
    assert "_setButtonBusy(rejectBtn" in body and "_clearButtonBusy(rejectBtn" in body


def test_preview_build_has_an_explicit_client_deadline():
    body = _top_level_fn(_read(), "_buildPreview")
    m = re.search(r"conversion/\$\{encodeURIComponent\(_campaignId\)\}/preview`,\s*\{\},\s*\{\s*timeoutMs:\s*(\d+)", body)
    assert m, "expected the preview POST to pass an explicit timeoutMs override"
    assert int(m.group(1)) >= 30000, "expected a generous deadline for a LaTeX/LibreOffice render"


def test_preview_build_guards_against_overlapping_calls():
    src = _read()
    assert "let _previewInFlight" in src, (
        "expected a module-level in-flight guard for _buildPreview"
    )
    body = _top_level_fn(src, "_buildPreview")
    assert "if (_previewInFlight)" in body, (
        "expected _buildPreview to attach to an existing in-flight build "
        "rather than firing a second overlapping POST"
    )
    assert "_previewInFlight = req" in body or "_previewInFlight = null" in body, (
        "expected the in-flight promise to actually be tracked/cleared"
    )


def test_preview_unavailable_message_still_renders_on_failure():
    body = _top_level_fn(_read(), "_buildPreview")
    assert "Preview unavailable:" in body


# ── #52: draft persistence ───────────────────────────────────────────────────


def test_draft_helpers_exist_and_use_sessionstorage():
    src = _read()
    for name in ("_saveDraft", "_restoreDraft", "_clearDraft", "_wireDraftListeners"):
        assert re.search(rf"function {name}\(", src), f"expected a {name}() helper"
    assert "sessionStorage.setItem" in src
    assert "sessionStorage.getItem" in src
    assert "sessionStorage.removeItem" in src


def test_draft_is_restored_and_wired_on_every_render():
    body = _top_level_fn(_read(), "_setBody")
    assert "_restoreDraft(body)" in body, "expected _setBody to restore a saved draft"
    assert "_wireDraftListeners(body)" in body, "expected _setBody to wire save-on-input"


def test_draft_is_cleared_once_a_step_actually_saves():
    src = _read()
    advance_body = _top_level_fn(src, "_advanceAndContinue")
    assert "_clearDraft(stepKey)" in advance_body, (
        "expected _advanceAndContinue to clear the just-saved step's draft"
    )
    next_intake_body = _top_level_fn(src, "_nextIntakeOrComplete")
    assert "_clearDraft()" in next_intake_body, (
        "expected _nextIntakeOrComplete to clear the just-saved intake section's draft"
    )


def test_draft_scope_is_set_per_step_and_per_intake_section():
    src = _read()
    render_step_body = _top_level_fn(src, "_renderStep")
    assert "_draftScope = step.key" in render_step_body

    render_intake_body = _top_level_fn(src, "_renderIntakeSection")
    assert re.search(r"_draftScope\s*=\s*`onboarding:\$\{key\}`", render_intake_body), (
        "expected each intake section to scope its draft independently"
    )


def test_settings_reused_steps_also_get_a_draft_scope():
    body = _top_level_fn(_read(), "mountSettingsStep")
    assert "_draftScope = stepKey" in body, (
        "expected mountSettingsStep to scope the draft so Settings-panel "
        "edits (channels/sandbox/fonts) also survive a reload"
    )


def test_draft_never_persists_password_type_fields():
    body = _top_level_fn(_read(), "_isDraftableField")
    assert "'password'" in body, "expected password-type fields to be excluded from the draft"
    assert "'file'" in body and "'hidden'" in body


def test_draft_denylist_excludes_credential_bearing_text_fields():
    src = _read()
    m = re.search(r"_DRAFT_EXCLUDE_IDS\s*=\s*new Set\(\[(.*?)\]\)", src, re.S)
    assert m, "expected an explicit _DRAFT_EXCLUDE_IDS denylist"
    denylist_body = m.group(1)
    # Discord webhook, Apprise/SMTP URL, and ntfy topic can all carry a secret
    # (bearer token / embedded password / secret channel) despite being plain
    # text inputs (type != password) — the hard rule for this fix is that none
    # of these are ever written to sessionStorage.
    for field_id in ("ao-ch-discord", "ao-ch-email", "ao-ch-ntfy"):
        assert field_id in denylist_body, f"expected {field_id} in the draft denylist"


def test_all_drafts_cleared_on_genuine_wizard_completion():
    src = _read()
    assert re.search(r"function _clearAllDrafts\(", src)
    dismiss_body = _top_level_fn(src, "_dismiss")
    assert "_clearAllDrafts()" in dismiss_body


def test_repeat_section_entries_are_scoped_by_card_index_not_just_name():
    """Work history/education/references reuse the SAME field `name` across
    every entry card — the draft key must disambiguate by entry, or typing in
    a second job entry would silently overwrite the first entry's draft."""
    body = _top_level_fn(_read(), "_draftFieldKey")
    assert ".ao-repeat-entry" in body
    assert "data-idx" in body
