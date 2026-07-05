"""Regression coverage for the copy & voice (exhaustive2 lens 02) pass confined
to THREE small front-door surfaces: applicantUpdate.js, applicantUpdateView.js,
and applicantGallery.js (see docs/design/audits/exhaustive2/02_copy_voice.md).

Findings fixed here:

- applicantUpdate.js
  * #144: the update-trigger failure toast said "The app's engine isn't
    reachable, so the update couldn't start." — "engine" is internal jargon
    and the sentence doesn't speak in the house first-person voice. Rewritten
    to "I couldn't start the update — Applicant isn't fully connected right
    now."
  * #171: the modal's `aria-label` was "Update applicant" (lowercase second
    word) while the view's own headline says "Update Applicant" — capitalized
    to match.

- applicantUpdateView.js
  * #145: the offline view's message repeated the same "engine" jargon —
    rewritten to "I can't check for updates right now — Applicant isn't fully
    connected yet. This page will work once it is."
  * #172: the no-updater note repeated "the way you first installed it"
    inside its own parenthetical of "the usual way" — rewritten to "Update
    once using the same method you first installed with, and the button will
    appear here afterwards."

- applicantGallery.js
  * #210: the "Nothing captured yet" empty state (a job search already
    exists, it just hasn't captured anything) reused `_createSearchCTA()`,
    the SAME "Create a job search" button as the true no-searches-yet state
    — routing an already-configured user back through setup/onboarding for no
    reason. Fixed with a new `_openAssistantCTA()` ("Open the Job Assistant")
    wired straight to `openApplicantChat()`, while the genuine no-searches
    empty state keeps `_createSearchCTA()` unchanged.

Every assertion below is a source-text check (matches this surface's existing
test convention — see test_applicant_backlog_warmempty.py's own "no browser,
no DOM... simple copy/text assertions" note). Each was verified failing by
temporarily reverting the exact source fix it protects (via a file-copy
backup, never `git stash`), confirming red, then restoring the fixed file
(clean `git diff` afterward) before landing this file.
"""

from __future__ import annotations

import pathlib

_REPO = pathlib.Path(__file__).resolve().parent.parent  # workspace/
_JS_DIR = _REPO / "static" / "js"
_UPDATE_JS = _JS_DIR / "applicantUpdate.js"
_UPDATE_VIEW_JS = _JS_DIR / "applicantUpdateView.js"
_GALLERY_JS = _JS_DIR / "applicantGallery.js"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# ── applicantUpdate.js ───────────────────────────────────────────────────────


def test_update_trigger_failure_toast_is_first_person_no_engine_jargon():
    js = _read(_UPDATE_JS)
    assert "The app's engine isn't reachable, so the update couldn't start." not in js
    assert (
        "I couldn't start the update — Applicant isn't fully connected right now."
        in js
    )


def test_update_modal_aria_label_capitalizes_applicant():
    js = _read(_UPDATE_JS)
    assert "aria-label', 'Update applicant'" not in js
    assert "aria-label', 'Update Applicant'" in js


# ── applicantUpdateView.js ───────────────────────────────────────────────────


def test_update_view_offline_message_is_first_person_no_engine_jargon():
    js = _read(_UPDATE_VIEW_JS)
    assert (
        "The app's engine isn't reachable, so updates can't be checked yet."
        not in js
    )
    assert (
        "I can't check for updates right now — Applicant isn't fully connected "
        "yet. This page will work once it is." in js
    )


def test_update_view_no_updater_message_drops_the_repetition():
    js = _read(_UPDATE_VIEW_JS)
    # The old copy said "the usual way (the way you first installed it)" —
    # the same idea stated twice in one clause.
    assert "the usual way (the way you first installed it)" not in js
    assert (
        "One-click updates aren't set up here yet. Update once using the same "
        "method you first installed with, and the button will appear here "
        "afterwards." in js
    )


# ── applicantGallery.js ──────────────────────────────────────────────────────


def test_gallery_no_searches_empty_state_keeps_create_search_cta():
    # The TRUE no-job-searches-yet state is unrelated to #210 and must be
    # untouched: it still offers "Create a job search".
    js = _read(_GALLERY_JS)
    assert "'No job searches yet'" in js
    assert "_createSearchCTA()" in js
    assert "Create a job search</button>" in js


def test_gallery_nothing_captured_yet_no_longer_offers_create_search_cta():
    js = _read(_GALLERY_JS)
    # Isolate the "Nothing captured yet" render call and confirm it no longer
    # reuses _createSearchCTA() (finding #210's wrong-CTA bug).
    idx = js.index("'Nothing captured yet'")
    following = js[idx : idx + 300]
    assert "_createSearchCTA()" not in following
    assert "_openAssistantCTA()" in following


def test_gallery_nothing_captured_yet_offers_open_job_assistant_cta():
    js = _read(_GALLERY_JS)
    assert "Open the Job Assistant</button>" in js
    assert "function _openAssistantCTA()" in js
    assert "function _wireOpenAssistantCTA()" in js
    # Wired straight to chat, not back through setup/onboarding.
    assert "_wireOpenAssistantCTA();" in js
