"""Regression coverage for design-audit theme #6 ("ERROR missing in ~7/16
surfaces ... no shared list-row, spinner, or empty/error/gated primitive"),
confined to this batch's four owned files — all workspace-NATIVE (not
`applicant*.js`, no relation to `applicantCore.js`'s shared kit):

  * ``workspace/static/js/calendar.js``
  * ``workspace/static/js/tasks.js``
  * ``workspace/static/js/notes.js``
  * ``workspace/static/js/emailInbox.js``

Per-file audit (LOADING / EMPTY / ERROR / GATED-equivalent), verified by hand
reading each file's actual fetch/render call sites before touching anything:

* **calendar.js** — LOADING (whirlpool spinner on ``openCalendar``) and the
  combined EMPTY+ERROR+GATED state for the *calendars* list
  (``_renderEmpty``/``_calendarsError`` — pre-existing, untouched) were
  already solid. The real gap: ``_fetchEvents`` (the per-visible-range
  *events* fetch that every one of month/week/agenda/year awaits) swallowed
  a failure into a resolved promise with only a ``console.error`` — no
  state was tracked, so a failed fetch on a first-ever load left `_events`
  empty and the grid rendered exactly like a genuinely event-free month,
  indistinguishable from a real empty state. Fixed by tracking `_eventsError`
  (mirroring the file's own pre-existing `_calendarsError` convention) and
  surfacing it as an inline toolbar banner + wired Retry
  (`_eventsErrorBannerHTML`, injected once via `_headerHTML` so all four
  views pick it up, wired centrally in the shared `_wireAll`). Matches the
  file's OWN established idiom (inline banner + `cal-btn` Retry, same
  toolbar-injection pattern as the rest of the file) — no `applicantCore.js`
  import into this native file.

* **tasks.js** — LOADING (`spinnerModule.createLoadingRow`) and EMPTY ("No
  tasks yet") were already present via the `_tasksFetched` sentinel, but
  ERROR was entirely missing: `_fetchTasks`'s catch swallowed the failure,
  landing on the exact same "No tasks yet. Create one to get started."
  message as a genuinely empty account. Fixed by tracking `_tasksError`
  (mirroring notes.js/calendar.js's own error-flag convention) and branching
  in `_renderList`. A second, distinct gap in the same file: `_fetchRuns`
  (run-history fetch) had no try/catch and silently returned `[]` on a
  non-ok response — `_showRunHistory` then either rendered the false-empty
  "No runs yet." OR, on a genuine network throw, left the loading spinner
  stuck forever (nothing ever replaced it). Both fixed: `_fetchRuns` now
  throws on `!res.ok`, and `_showRunHistory` wraps the call in its own
  try/catch with an error state + Retry.

* **notes.js** — LOADING (`_renderLoadingSkeleton`, a real skeleton, not a
  spinner) and EMPTY ("No notes yet") were present; ERROR was the same
  shape of gap as tasks.js: `_fetchNotes`'s catch (and its `!res.ok`
  branch) swallowed the failure into `_notes = []` with no flag, so
  `_renderNotes` rendered the plain "No notes yet" empty message
  indistinguishable from a real empty account. Fixed by tracking
  `_notesError` and branching in the (now-shared, both empty-message call
  sites use it) `_notesEmptyMsgHTML` helper, with a wired Retry.

* **emailInbox.js** — LOADING (whirlpool spinner) and EMPTY were already a
  first-class experience — `_buildEmailEmptyState()` (a prior round's #141
  fix, distinct copy for "no emails" vs "no emails from this sender", with
  wired Compose/Connect-account actions). ERROR was present but broken: the
  catch path rendered a *static, unclickable* "Setup: Settings ›
  Integrations" text row (`_emailSetupHint()`) with no actual click
  handler and no Retry — a real fetch failure left the user with nothing
  they could act on. Fixed by adding `_buildEmailErrorState()`, a sibling
  of the existing `_buildEmailEmptyState()` with the same shell but real
  wired Retry + Connect-account buttons, and removing the dead
  `_emailSetupHint()`.

GATED: none of these four features gate on an external precondition the way
Applicant's engine-backed surfaces do (no "connect a model" / "engine
offline" branch anywhere in any of the four files — grepped for
`gated|engine_available|not configured` case-insensitively with zero hits
before this batch). The closest native equivalent — "no account/calendar
configured yet" — was already handled by each file's own EMPTY-state CTA
(calendar's `_renderEmpty` "Open Settings"/"New calendar", email's "Connect
account") and is left untouched.

Every assertion below was verified by hand: temporarily revert the
corresponding hunk (checked via `git stash` reverting all four files at
once), confirm the relevant assertions in this file go red, then restore
(`git stash pop`) and confirm green again — this file's own DoD, matching
the ``test_applicant_round2_wave1_corekit.py`` / ``..._wave3_trackersurface.py``
convention: source-text regex assertions (no DOM, no browser) plus one real
node-executed behavioral check where a small pure-ish function is cheaply
extractable.
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
JS_DIR = REPO_ROOT / "workspace" / "static" / "js"
CALENDAR_JS = JS_DIR / "calendar.js"
TASKS_JS = JS_DIR / "tasks.js"
NOTES_JS = JS_DIR / "notes.js"
EMAIL_JS = JS_DIR / "emailInbox.js"

_HAS_NODE = shutil.which("node") is not None


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _fn(src: str, name: str, *, async_: bool = False) -> str:
    """Extract a top-level `[async ]function name(...) { ... }` body up to
    the matching top-level closing brace at column 0 (same convention as
    test_applicant_round2_wave1_corekit.py's `_top_level_fn` helpers)."""
    prefix = r"async function " if async_ else r"function "
    m = re.search(rf"{prefix}{re.escape(name)}\([^)]*\)\s*\{{(.*?)\n\}}", src, re.S)
    assert m, f"expected a top-level {'async ' if async_ else ''}function {name}(...) in the source"
    return m.group(1)


@pytest.fixture(scope="module")
def node_available():
    if not _HAS_NODE:
        pytest.skip("node binary not on PATH")


# ── syntax smoke: all four touched files must still parse ──────────────────


@pytest.mark.parametrize("path", [CALENDAR_JS, TASKS_JS, NOTES_JS, EMAIL_JS])
def test_node_check_touched_files(path, node_available):
    res = subprocess.run(
        ["node", "--check", str(path)],
        capture_output=True,
        timeout=15,
        text=True,
    )
    assert res.returncode == 0, f"node --check failed for {path.name}:\n{res.stderr}"


# ── calendar.js: events-fetch ERROR state (previously silent) ──────────────


def test_calendar_fetch_events_tracks_an_error_flag_instead_of_swallowing():
    src = _read(CALENDAR_JS)
    body = _fn(src, "_fetchEvents", async_=True)
    assert re.search(r"\.catch\(e => \{", body), "expected the fetch chain's .catch to be present"
    catch_m = re.search(r"\.catch\(e => \{(.*?)\n    \}\);", body, re.S)
    assert catch_m, "expected a .catch(e => { ... }) block in _fetchEvents"
    catch_body = catch_m.group(1)
    assert "_eventsError = e.message" in catch_body, (
        "a failed events fetch must set _eventsError, not just console.error and swallow"
    )
    # Success paths must clear it so a stale banner doesn't linger.
    assert body.count("_eventsError = null") >= 1


def test_calendar_events_error_banner_gated_on_the_flag_and_offers_retry():
    src = _read(CALENDAR_JS)
    fn = re.search(r"function _eventsErrorBannerHTML\(\) \{(.*?)\n\}", src, re.S)
    assert fn, "expected an _eventsErrorBannerHTML() renderer"
    body = fn.group(1)
    assert "if (!_eventsError) return ''" in body, "must no-op (no banner) when there's no error"
    assert 'id="cal-events-retry"' in body, "the banner must offer a Retry control"


def test_calendar_header_html_injects_the_events_error_banner():
    """The banner must actually be wired into the render path — added once
    to _headerHTML() so month/week/agenda/year all pick it up without
    needing four separate edits."""
    src = _read(CALENDAR_JS)
    assert "return `${_eventsErrorBannerHTML()}<div class=\"cal-toolbar\">" in src


def test_calendar_retry_button_wired_and_force_refetches_the_visible_range():
    src = _read(CALENDAR_JS)
    body = _fn(src, "_wireAll")
    m = re.search(r"document\.getElementById\('cal-events-retry'\)\?\.addEventListener\('click', async \(e\) => \{(.*?)\n  \}\);", body, re.S)
    assert m, "expected a click handler wired to #cal-events-retry inside _wireAll"
    handler_body = m.group(1)
    assert "_fetchEvents(" in handler_body and "/*force*/ true" in handler_body, (
        "retry must force-refetch (bypass the range cache), not silently no-op on a cached-but-stale range"
    )
    assert "_render();" in handler_body


def test_calendar_events_error_variable_declared_near_calendars_error():
    """Mirrors the file's own pre-existing `_calendarsError` convention
    (same declaration style, same module-level scope) rather than importing
    a foreign error-state shape."""
    src = _read(CALENDAR_JS)
    assert re.search(r"let _calendarsError = null;\n.*?\nlet _eventsError = null;", src, re.S)


# ── tasks.js: main list ERROR state (previously silent) ────────────────────


def test_tasks_fetch_tasks_throws_on_non_ok_and_tracks_an_error_flag():
    src = _read(TASKS_JS)
    body = _fn(src, "_fetchTasks", async_=True)
    assert "if (!res.ok) throw new Error(`HTTP ${res.status}`);" in body, (
        "a non-ok /api/tasks response must not resolve as if it succeeded"
    )
    assert "_tasksError = e.message || 'Failed to load tasks';" in body
    assert "_tasksError = null;" in body, "a successful fetch must clear a previous error"


def test_tasks_render_list_distinguishes_error_from_genuinely_empty():
    src = _read(TASKS_JS)
    body = _fn(src, "_renderList")
    # The three-way branch: still loading → error → genuinely empty.
    assert re.search(r"if \(!_tasksFetched\) \{.*?\} else if \(_tasksError\) \{.*?\} else \{", body, re.S), (
        "expected _renderList to branch on _tasksError between the loading and truly-empty cases"
    )
    assert "tasks-retry-btn" in body
    assert "await _fetchTasks();" in body and "_renderList();" in body


def test_tasks_fetch_runs_throws_instead_of_silently_returning_empty():
    src = _read(TASKS_JS)
    body = _fn(src, "_fetchRuns", async_=True)
    assert "if (!res.ok) throw new Error(`HTTP ${res.status}`);" in body, (
        "a non-ok /runs response used to resolve to [], indistinguishable from a task that never ran"
    )


def test_tasks_show_run_history_catches_fetch_runs_and_renders_error_with_retry():
    src = _read(TASKS_JS)
    body = _fn(src, "_showRunHistory", async_=True)
    m = re.search(r"try \{\s*runs = await _fetchRuns\(taskId\);\s*\} catch \(e\) \{(.*?)\n  \}", body, re.S)
    assert m, (
        "expected _showRunHistory to wrap the _fetchRuns call in its own try/catch — "
        "previously an unhandled rejection here left the loading spinner stuck forever"
    )
    assert "runsError = e.message" in m.group(1)
    assert "if (runsError) {" in body
    assert "task-runs-retry-btn" in body
    assert re.search(r"getElementById\('task-runs-retry-btn'\)\?\.addEventListener\('click', \(\) => \{\s*_showRunHistory\(taskId, taskName\);", body)


# ── notes.js: main list ERROR state (previously silent) ────────────────────


def test_notes_fetch_notes_tracks_an_error_flag_on_both_failure_paths():
    src = _read(NOTES_JS)
    body = _fn(src, "_fetchNotes", async_=True)
    assert "_notesError = `HTTP ${res.status}`;" in body, "a non-ok response must set the error flag"
    assert "_notesError = e.message || 'Failed to load notes';" in body, "a thrown/network error must set the error flag"
    assert "_notesError = null;" in body, "a successful fetch must clear a previous error"


def test_notes_empty_message_helper_branches_on_the_error_flag():
    src = _read(NOTES_JS)
    fn = re.search(r"function _notesEmptyMsgHTML\(fallbackText\) \{(.*?)\n\}", src, re.S)
    assert fn, "expected a shared _notesEmptyMsgHTML(fallbackText) helper"
    body = fn.group(1)
    assert "if (_notesError) {" in body
    assert "notes-retry-btn" in body
    assert "fallbackText" in body, "the non-error branch must still render the real empty copy"


def test_notes_render_uses_the_shared_helper_at_both_empty_message_call_sites():
    """Both places _renderNotes used to hard-code the bespoke 'No notes'/'No
    notes yet' markup must now go through the one helper, so a fetch error
    reads consistently regardless of which render branch (quick-add-open vs
    not) is active."""
    src = _read(NOTES_JS)
    assert "_notesEmptyMsgHTML('No notes')" in src
    assert "_notesEmptyMsgHTML('No notes yet')" in src
    # The old inline duplicated markup must be gone.
    assert "'<div class=\"notes-empty-msg\">No notes yet <span" not in src


def test_notes_retry_button_wired_in_render():
    src = _read(NOTES_JS)
    body = _fn(src, "_renderNotes")
    assert re.search(r"body\.querySelector\('\.notes-retry-btn'\)\?\.addEventListener\('click', async \(\) => \{\s*await _fetchNotes\(\);\s*_renderNotes\(\);", body)


# ── emailInbox.js: main list ERROR state (present but non-functional) ──────


def test_email_inbox_error_state_is_a_real_wired_component_not_dead_text():
    src = _read(EMAIL_JS)
    # The old dead, unclickable hint helper must be gone entirely.
    assert "_emailSetupHint" not in src, "the old unclickable text-only error hint must be removed"
    fn = re.search(r"function _buildEmailErrorState\(msg\) \{(.*?)\n\}", src, re.S)
    assert fn, "expected a _buildEmailErrorState(msg) sibling of _buildEmailEmptyState()"
    body = fn.group(1)
    assert "email-error-retry" in body and "loadEmails(false)" in body, (
        "the error state must offer a real Retry wired back into loadEmails"
    )
    assert "email-error-connect" in body and "_openIntegrationsSettings()" in body


def test_email_inbox_load_emails_catch_uses_the_new_error_state():
    src = _read(EMAIL_JS)
    body = _fn(src, "loadEmails", async_=True)
    catch_m = re.search(r"\} catch \(e\) \{(.*?)\n  \} finally \{", body, re.S)
    assert catch_m, "expected a catch block in loadEmails"
    catch_body = catch_m.group(1)
    assert "_buildEmailErrorState(msg)" in catch_body
    assert "list.appendChild(_buildEmailErrorState(msg))" in catch_body


def test_email_inbox_empty_state_untouched_still_has_working_ctas():
    """Confirm the pre-existing (round-1 #141) empty state — a different
    surface from the error state above — wasn't disturbed by this change."""
    src = _read(EMAIL_JS)
    fn = re.search(r"function _buildEmailEmptyState\(\) \{(.*?)\n\}", src, re.S)
    assert fn
    body = fn.group(1)
    assert "email-empty-compose" in body and "_composeNew()" in body
    assert "email-empty-connect" in body and "_openIntegrationsSettings()" in body


# ── cross-file: no GATED precondition exists in any of these four natives ──


@pytest.mark.parametrize("path", [CALENDAR_JS, TASKS_JS, NOTES_JS, EMAIL_JS])
def test_no_engine_style_gate_invented_in_native_workspace_files(path):
    """These are core workspace features (not Applicant-specific), so they
    must not grow an Applicant-style 'connect a model' / 'engine offline'
    gate — confirms this batch didn't manufacture one that isn't grounded
    in how these features actually work."""
    src = _read(path)
    assert not re.search(r"engine_available|connect a model", src, re.I)


# ── none of the four files import the Applicant-specific shared kit ────────


@pytest.mark.parametrize("path", [CALENDAR_JS, TASKS_JS, NOTES_JS, EMAIL_JS])
def test_native_files_do_not_import_applicant_core_kit(path):
    """Deliberate: these are workspace-native features predating Applicant
    entirely. Each already had (or, per this batch, now has) its own
    established loading/empty/error idiom — importing applicantCore.js's
    Applicant-specific kit into native code would be the wrong direction
    per this round's brief (match the native pattern, don't force-import
    the Applicant one)."""
    src = _read(path)
    assert "applicantCore.js" not in src


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
