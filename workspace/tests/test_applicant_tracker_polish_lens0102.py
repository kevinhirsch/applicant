"""Regression coverage for the lens 01 (micro-interactions) + lens 02 (copy &
voice) polish pass on the Tracker board (``workspace/static/js/
applicantTracker.js``).

Neither ``docs/design/audits/exhaustive2/01_micro_interactions.md`` nor
``docs/design/audits/exhaustive2/02_copy_voice.md`` cites this file by
``file:line`` — both were written against ``applicant*.js`` before the
Tracker board existed (it closes gaps enumerated in a different audit,
``08_engine_dark_matrix.md``). Per those two docs' own stated scope
("Every user-facing string in the Applicant lane — front-door JS surfaces
(``workspace/static/js/applicant*.js`` ...)" and the cross-cutting rules
"fix once, fixes dozens"), this file still owes the exact same house-voice
and busy-state conventions. This test locks in the real violations of those
cross-cutting rules found in the current source and fixed here:

Copy (house voice — cross-cutting #1/#3/#4 in the copy audit):
  - third-person self-reference ("your assistant", "Applicant", "the
    assistant") wherever the agent is the sentence's actor -> first person
    ("I"/"I'll"/"me").
  - "campaign" (CRM vocabulary) in a user-facing string -> "search".
  - "session" jargon on the takeover-surface link/tooltip -> "live view",
    aligned with the Portal fix for the same surface (finding #24).
  - straight apostrophes in copy -> curly (E2019).

Micro-interactions (Tier 3 busy-state pattern already established
elsewhere in this very file -- every other in-flight action handler here
guards re-entry with ``_busyIds.has(id)`` and shows a transient busy label;
two call sites were missing that same guard):
  - ``_recordOutcome`` (the per-row "Record what happened" select) did not
    check ``_busyIds`` before starting, unlike every sibling handler.
  - ``_archiveApplication`` disabled the button but never showed a
    transient "Archiving..." label the way ``_retryStuck`` /
    ``_overrideBlocked`` / ``_onMarkSubmitted`` / ``_onDetectSubmission`` do.

Every assertion below was verified, by hand, to go red against a restored
pre-fix copy of the file (backed up to ``/tmp/.../applicantTracker.js.orig``
before editing) and green again after re-applying the fix.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest

_REPO = pathlib.Path(__file__).resolve().parent.parent  # workspace/
_TRACKER_JS = _REPO / "static" / "js" / "applicantTracker.js"

_HAS_NODE = shutil.which("node") is not None


def _src() -> str:
    return _TRACKER_JS.read_text(encoding="utf-8")


# ══════════════════════════════════════════════════════════════════════════
# Copy — first-person voice (never "your assistant" / "Applicant" / "the
# assistant" as the sentence's actor in a user-facing string)
# ══════════════════════════════════════════════════════════════════════════


def test_no_third_person_assistant_in_user_facing_copy():
    src = _src()
    banned_strings = [
        "Once your assistant submits an application",
        "your assistant is connected and running",
        "Applicant couldn't resume this",
        "Applicant will pick this back up",
        "Applicant will start this application",
        "Ask Applicant to check the live session",
        "the assistant is using for this application",
    ]
    for needle in banned_strings:
        assert needle not in src, f"third-person self-reference leaked back in: {needle!r}"


def test_empty_and_offline_states_speak_first_person():
    src = _src()
    assert "Once I submit an application, it shows up here so you can follow where it stands." in src
    assert (
        "Once I submit an application, it shows up here — applied, awaiting a response, "
        in src
    )
    assert "Your tracker will appear here once I’m connected and running." in src


def test_stuck_and_retry_toasts_speak_first_person():
    src = _src()
    assert "I couldn’t resume this after" in src
    assert "I’ll pick this back up on my next pass." in src
    assert "I’ll start this application on my next pass." in src
    assert "Ask me to check the live session for a confirmation page" in src


# ══════════════════════════════════════════════════════════════════════════
# Copy — terminology drift ("campaign" -> "search"), curly apostrophes,
# and "session" jargon on the takeover-surface link (aligned with the
# Portal fix for the same surface, copy audit finding #24)
# ══════════════════════════════════════════════════════════════════════════


def test_no_bare_campaign_word_in_user_facing_copy():
    src = _src()
    assert "No campaign on this application yet." not in src
    assert "No search linked to this application yet." in src


def test_sandbox_session_link_uses_watch_live_not_session_jargon():
    src = _src()
    assert "Open live session" not in src
    assert "\n        Watch live\n      </a>" in src
    assert "Watch the live browser view I’m using for this application" in src


def test_curly_apostrophes_in_fixed_copy_strings():
    src = _src()
    # Straight-apostrophe forms that used to ship in these exact strings must
    # be gone; the curly replacements must be present.
    assert "Haven't heard back" not in src
    assert "Haven’t heard back" in src
    assert "Couldn't confirm it automatically" not in src
    assert "Couldn’t confirm it automatically" in src
    assert "Didn't recognize anything in that email." not in src
    assert "Didn’t recognize anything in that email." in src
    assert "Prep notes aren't ready yet." not in src
    assert "Prep notes aren’t ready yet." in src


# ══════════════════════════════════════════════════════════════════════════
# Micro-interactions — busy-state guards matching the rest of this file's
# own established convention
# ══════════════════════════════════════════════════════════════════════════


def test_record_outcome_guards_reentry_while_busy():
    src = _src()
    start = src.index("async function _recordOutcome(select) {")
    end = src.index("\n}\n", start)
    block = src[start:end]
    assert "_busyIds.has(applicationId)" in block, (
        "_recordOutcome must guard re-entry with the same _busyIds check "
        "every sibling handler in this file uses"
    )


def test_archive_application_shows_transient_busy_label():
    src = _src()
    start = src.index("async function _archiveApplication(btn) {")
    end = src.index("\n}\n", start)
    block = src[start:end]
    assert "origLabel" in block, "_archiveApplication must capture the original label"
    assert "Archiving…" in block, "_archiveApplication must show a transient busy label"
    assert "btn.textContent = origLabel" in block, (
        "_archiveApplication must restore the label on failure, matching "
        "_retryStuck/_overrideBlocked/_onMarkSubmitted/_onDetectSubmission"
    )


# ══════════════════════════════════════════════════════════════════════════
# Syntax sanity (front-end has no bundler/build step -- node --check only)
# ══════════════════════════════════════════════════════════════════════════


def test_node_check_syntax():
    if not _HAS_NODE:
        pytest.skip("node binary not on PATH")
    result = subprocess.run(
        ["node", "--check", str(_TRACKER_JS)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
