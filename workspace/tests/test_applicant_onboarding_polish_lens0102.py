"""Regression coverage for the exhaustive2 audit pass on
``workspace/static/js/applicantOnboarding.js`` (the OOBE wizard / Settings
step renderers), combining the residual findings from:

* ``docs/design/audits/exhaustive2/02_copy_voice.md`` (lens 02, copy/voice) —
  the file's straight-vs-curly apostrophe drift (#74) and résumé/resume
  spelling drift (#82) left over after the earlier
  ``test_applicant_copy_onboarding_lens02.py`` pass (that file's own
  docstring notes #36's ``NEVER_DOES`` list and #51's Welcome step-desc are
  DELIBERATELY left third-person — both strings are duplicated verbatim into
  files outside this pass, guarded by their own drift tests — so neither is
  touched or re-asserted here).

* ``docs/design/audits/exhaustive2/01_micro_interactions.md`` (lens 01,
  micro-interactions) — findings #21, #22, #23, #26, #47, #60, #90 and #96,
  all confined to this same file. (#4, #5, #12, #29a/#43, #76, #78, #79 were
  already landed by earlier passes — see ``test_applicant_onboarding_
  resilience_lens04.py`` and ``test_applicant_copy_onboarding_lens02.py`` —
  and are not re-asserted here. #91, the résumé double-upload into
  ``/fonts/detect``, needs an engine-side change outside this file's
  boundary and is left as a follow-up.)

Follows the established convention (see the two sibling files above): every
fact is read from the actual static file content via ``pathlib`` — no
browser, no DOM, no real socket. Each assertion here was verified, by hand,
to go red when the underlying fix is reverted (temporarily restored the
pre-fix source from a file-copy backup, reran, saw a real
``AssertionError``, then restored the fix from the backup — never
``git stash``) before this file was landed.
"""

from __future__ import annotations

import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
JS_DIR = REPO_ROOT / "workspace" / "static" / "js"
ONBOARDING_JS = JS_DIR / "applicantOnboarding.js"


def _read() -> str:
    return ONBOARDING_JS.read_text(encoding="utf-8")


# ── Copy/voice lens 02: apostrophe drift (#74) ──────────────────────────────


def test_resume_health_hints_use_curly_apostrophes():
    js = _read()
    assert "We couldn’t pull readable text out of this file" in js
    assert "We couldn't pull readable text out of this file" not in js
    assert "If it’s a scanned image" in js
    assert "If it's a scanned image" not in js
    assert "Your email address isn’t detectable in the text" in js
    assert "Your email address isn't detectable in the text" not in js
    assert "Check that it isn’t inside a text box" in js
    assert "Check that it isn't inside a text box" not in js


def test_readiness_banner_and_timezone_tooltip_use_curly_apostrophes():
    js = _read()
    assert "just makes your applications smoother — it’s all optional." in js
    assert "just makes your applications smoother — it's all optional." not in js
    assert "Defaults to your browser’s own time zone" in js
    assert "Defaults to your browser\\'s own time zone" not in js


def test_inline_font_prompt_uses_curly_apostrophe():
    js = _read()
    assert "uses fonts that aren’t installed yet" in js
    assert "uses fonts that aren't installed yet" not in js


def test_desktop_help_locked_straight_apostrophe_is_untouched():
    """The desktop-help button title is asserted VERBATIM (straight apostrophe)
    by test_applicant_copy_onboarding_lens02.py::
    test_desktop_help_is_first_person_and_available_state_keeps_action_label —
    confirm this pass didn't accidentally curly-ify it and break that guard."""
    js = _read()
    assert 'title="Let me help with desktop steps the browser can\'t reach"' in js


# ── Copy/voice lens 02: résumé/resume spelling drift (#82) ──────────────────


def test_fonts_step_says_resume_with_accent_throughout():
    js = _read()
    assert "your generated résumé look exactly like yours" in js
    assert "your generated resume look exactly like yours" not in js
    assert "the fonts your résumé uses" in js
    assert "Upload a résumé to check" in js
    assert "check which fonts your résumé needs" in js
    assert "so your generated résumé keeps its look." in js
    assert ">Choose a résumé…</button>" in js
    assert ">Choose a resume…</button>" not in js


def test_inline_font_prompt_and_resume_read_status_say_resume_with_accent():
    js = _read()
    assert "Your résumé uses fonts that aren’t installed yet." in js
    assert "generated résumé keeps its look." in js
    assert "Reading your résumé…" in js
    assert "Reading your resume…" not in js
    assert "Could not read the résumé." in js


def test_resume_health_prose_says_resume_with_accent():
    js = _read()
    assert "this résumé should read cleanly in most application-tracking systems" in js
    assert "helps automated systems parse your résumé correctly." in js


# ── Micro-interactions lens 01: #21 mobile keyboard hints ───────────────────


def test_field_html_adds_autocomplete_and_inputmode_hints():
    js = _read()
    assert "f.type === 'email' ? ' autocomplete=\"email\"'" in js
    assert "f.type === 'tel' ? ' autocomplete=\"tel\"'" in js
    assert "f.type === 'number' ? ' inputmode=\"numeric\"'" in js


# ── Micro-interactions lens 01: #22 EEO detail rehydrate + show/hide ────────


def test_eeo_detail_input_rehydrates_and_toggles_with_its_select():
    js = _read()
    # The detail input must read back its OWN saved value...
    assert (
        'data-eeo-detail="${esc(f.name)}"' in js
    ), "eeo detail input must carry a hook so its select can toggle it"
    assert 'value="${esc(dv)}"' in js, "eeo detail input must rehydrate from saved data, not always render blank"
    assert "const dv = detailValue == null ? '' : detailValue;" in js
    # ...and stay hidden unless the paired select says "prefer to answer".
    assert "const showDetail = (v || 'decline to self-identify') === 'prefer to answer';" in js
    assert "showDetail ? '' : 'display:none;'" in js
    assert "data-eeo-select=\"${esc(f.name)}\"" in js
    assert "[data-eeo-select]" in js
    assert "sel.value === 'prefer to answer' ? '' : 'none'" in js
    # The call site must actually pass the saved detail value through.
    assert "_fieldHTML(f, saved[f.name], saved[`${f.name}__detail`])" in js


# ── Micro-interactions lens 01: #23 intake form Enter-to-continue ──────────


def test_intake_form_has_a_submit_handler_and_autofocuses_first_field():
    js = _read()
    assert "intakeForm.onsubmit = (e) => {" in js
    assert "e.preventDefault();" in js
    assert "if (next && !next.disabled) next.click();" in js
    assert "if (firstField) firstField.focus();" in js


# ── Micro-interactions lens 01: #26 email-backstop clamp reflects + says so ─


def test_email_backstop_clamp_is_reflected_and_announced():
    js = _read()
    assert "const wasClamped = Number.isFinite(raw) && raw !== minutes;" in js
    assert "timeoutInput.value = minutes;" in js
    assert "Capped at ${minutes} minutes — saved." in js
    # The un-clamped happy path must still read exactly as the lens02 pass left it.
    assert "Saved — I’ll email you after ${minutes} minutes." in js


# ── Micro-interactions lens 01: #47 nav dims/disables while a step is busy ──


def test_nav_busy_watch_disables_back_and_skip_while_busy():
    js = _read()
    assert "function _startNavBusyWatch() {" in js
    assert "function _stopNavBusyWatch() {" in js
    assert "btn.disabled = _busy;" in js
    assert "_startNavBusyWatch();" in js
    assert "_stopNavBusyWatch();" in js


# ── Micro-interactions lens 01: #60 aria-current omitted, not "false" ───────


def test_rail_omits_aria_current_instead_of_literal_false():
    js = _read()
    assert 'aria-current="${isCur ? \'step\' : \'false\'}"' not in js
    assert "const ariaCurrent = isCur ? ' aria-current=\"step\"' : '';" in js
    assert "aria-disabled=\"true\"${ariaCurrent}>" in js


# ── Micro-interactions lens 01: #90 quiet-hours second select has a real label ─


def test_quiet_hours_email_select_has_an_accessible_label():
    js = _read()
    assert '<label class="settings-label">&nbsp;</label>' not in js
    assert 'aria-label="Email during quiet hours"' in js


# ── Micro-interactions lens 01: #96 sandbox secrets surface a saved-marker ──


def test_sandbox_secrets_show_inline_saved_marker_like_sibling_fields():
    js = _read()
    assert (
        "cur.configured ? '•••• already saved — leave blank to keep' : 'secret'"
        in js
    )
    assert (
        "cur.configured ? '•••• already saved — leave blank to keep' : 'password'"
        in js
    )
