"""Step bindings for the N3 theme — workspace JS robustness / silent catches.

Issues #327 (chat.js bare JSON.parse), #328 (notes.js empty catches), #329
(emailInbox.js empty import catches), #330 (assistant.js swallowed import), #331
(document.js empty catches / TODOs), #334 (UMBRELLA: workspace JS silent catches),
#352 (cookbookRunning.js shell calls + catches).

These are **JS-file-content facts**, so every assertion is made by reading the
``.js`` source with ``pathlib`` (``ROOT = parents[3]``) and matching the risky /
safe pattern with a regex — no browser, no DOM, no network.

Convention (mirrors ``test_enh_t08_frontend_steps.py`` / ``test_enh_t09_deadcode_steps.py``):

* Scenarios with NO ``@pending`` tag are REAL regression coverage for a robustness
  fix that already ships on this branch (a JSON.parse now wrapped in ``try``, a
  localStorage read guarded, a delete handler that shows an error, the file having
  no work markers, the shell-exec wiring that exists). They must pass today.
* Scenarios tagged ``@pending`` are TDD acceptance specs for the residual gap: the
  risky pattern (an empty ``.catch(() => {})`` / bare ``catch {}``, an unguarded
  ``localStorage`` write, an unescaped innerHTML interpolation) is STILL present, so
  the "it is GONE" assertion genuinely fails → ``conftest.pytest_bdd_apply_tag``
  maps ``@pending`` to a non-strict xfail. When the cleanup lands, drop the tag and
  the scenario becomes a hard regression gate. No ``assert True``.
"""

from __future__ import annotations

import pathlib
import re

import pytest
from pytest_bdd import given, scenarios, then, when

scenarios(
    "../features/enhancements/enh_327_chat_json_parse_guard.feature",
    "../features/enhancements/enh_328_notes_mutation_feedback.feature",
    "../features/enhancements/enh_329_emailinbox_import_feedback.feature",
    "../features/enhancements/enh_330_assistant_chat_import_feedback.feature",
    "../features/enhancements/enh_331_document_storage_guard.feature",
    "../features/enhancements/enh_334_workspace_js_silent_catches.feature",
    "../features/enhancements/enh_352_cookbook_shell_safety.feature",
)

# Repo root: this file is tests/bdd/steps/<this>.py → parents[3] is the repo root.
ROOT = pathlib.Path(__file__).resolve().parents[3]
JS = ROOT / "workspace" / "static" / "js"

# --- shared regexes ---------------------------------------------------------
# An empty arrow catch: .catch(() => {}) (optionally a named arg, optional whitespace).
EMPTY_ARROW_CATCH = re.compile(r"\.catch\(\s*\(?\s*[A-Za-z_]*\s*\)?\s*=>\s*\{\s*\}\s*\)")
# A bare empty catch block: catch {} or catch (e) {} with nothing inside.
EMPTY_BARE_CATCH = re.compile(r"catch\s*(?:\([A-Za-z_$]*\))?\s*\{\s*\}")
WORK_MARKER = re.compile(r"\b(?:TODO|FIXME|HACK)\b")


def _read(name: str) -> str:
    return (JS / name).read_text(encoding="utf-8", errors="ignore")


def _silent_catch_count(text: str) -> int:
    return len(EMPTY_ARROW_CATCH.findall(text)) + len(EMPTY_BARE_CATCH.findall(text))


@pytest.fixture
def n3ctx() -> dict:
    return {}


# ===========================================================================
# #327 — chat.js bare JSON.parse on stream chunk data
# ===========================================================================
@given("the chat browser module")
def given_chat(n3ctx):
    n3ctx["src"] = _read("chat.js")


@when("the stream chunk JSON parsing is inspected")
def inspect_chat_parse(n3ctx):
    lines = n3ctx["src"].splitlines()
    # Every JSON.parse line must have "try" on its own or the immediately prior line.
    unguarded = []
    for i, line in enumerate(lines):
        if "JSON.parse" in line:
            prev = lines[i - 1] if i > 0 else ""
            if "try" not in line and "try" not in prev:
                unguarded.append(i + 1)
    n3ctx["chat_unguarded_parse"] = unguarded


@then("every parse of a stream chunk sits inside a try block")
def chat_parse_guarded(n3ctx):
    # GREEN: both cited bare JSON.parse calls (L1332, L4263) are now wrapped in try.
    assert n3ctx["chat_unguarded_parse"] == [], (
        f"JSON.parse calls not wrapped in try at lines: {n3ctx['chat_unguarded_parse']}"
    )


@when("the chunk parse failure handling is inspected")
def inspect_chat_parse_failure(n3ctx):
    n3ctx["chat_logs_parse_err"] = "Error parsing SSE data" in n3ctx["src"]


@then("the parse failure is logged instead of crashing the handler")
def chat_parse_logged(n3ctx):
    # GREEN: the stream loop's catch logs console.error('Error parsing SSE data', e).
    assert n3ctx["chat_logs_parse_err"], "stream parse failure is not logged"


@when("the module is scanned for empty catch handlers")
def scan_chat_empty_catch(n3ctx):
    n3ctx["empty_catches"] = _silent_catch_count(n3ctx["src"])


@then("no empty arrow catch or empty bare catch block remains")
def chat_no_empty_catch(n3ctx):
    # @pending: chat.js still ships several empty .catch(() => {}) / catch {} blocks.
    assert n3ctx["empty_catches"] == 0, (
        f"chat.js still has {n3ctx['empty_catches']} silent catch blocks"
    )


# ===========================================================================
# #328 — notes.js empty catches on note mutations
# ===========================================================================
@given("the notes browser module")
def given_notes(n3ctx):
    n3ctx["src"] = _read("notes.js")


@when("the single-card delete handler is inspected")
def inspect_notes_delete(n3ctx):
    # The card-trash delete handler restores the note and shows an error on failure.
    n3ctx["notes_delete_feedback"] = bool(
        re.search(
            r"_deleteNoteApi\([^)]*\)\.then\(.*?\)\.catch\(\s*\(\s*\)\s*=>\s*\{"
            r".*?showError\(\s*['\"]Failed to delete",
            n3ctx["src"],
            re.S,
        )
    )


@then("a failed delete shows an error message to the user")
def notes_delete_feedback(n3ctx):
    # GREEN: at least one delete path rolls back and calls uiModule.showError(...).
    assert n3ctx["notes_delete_feedback"], (
        "no note delete handler surfaces an error on failure"
    )


@when("the note mutation calls are scanned")
def scan_notes_mutations(n3ctx):
    # Count _patchNote(...) / _deleteNoteApi(...) calls ending in an EMPTY catch.
    pat = re.compile(
        r"_(?:patchNote|deleteNoteApi)\([^;]*?\.catch\(\s*\(?\s*[A-Za-z_]*\s*\)?\s*=>\s*\{\s*\}\s*\)"
    )
    n3ctx["notes_silent_mutations"] = pat.findall(n3ctx["src"])


@then("no note patch or delete call ends in an empty catch handler")
def notes_no_silent_mutation(n3ctx):
    # @pending: many note mutations still end in .catch(() => {}) (e.g. L880, L1288, L2403).
    count = len(n3ctx["notes_silent_mutations"])
    assert count == 0, f"{count} note mutations still swallow their failure silently"


# ===========================================================================
# #329 — emailInbox.js empty ui.js import catches + localStorage
# ===========================================================================
@given("the email inbox browser module")
def given_inbox(n3ctx):
    n3ctx["src"] = _read("emailInbox.js")


@when("the unread-dot last-seen read is inspected")
def inspect_inbox_read(n3ctx):
    # The getItem for the last-seen UID sits inside the unread-dot try/catch.
    src = n3ctx["src"]
    idx = src.find("applicant-email-last-seen-uid")
    assert idx != -1, "last-seen UID key not found"
    # Walk back to the nearest 'try {' / 'catch' to confirm the read is in a try body.
    before = src[:idx]
    last_try = before.rfind("try {")
    last_catch = before.rfind("} catch")
    n3ctx["inbox_read_guarded"] = last_try > last_catch


@then("the localStorage access is wrapped in a try block")
def inbox_read_guarded(n3ctx):
    # GREEN: the getItem read is inside the unread-dot computation's try/catch.
    assert n3ctx["inbox_read_guarded"], "last-seen UID read is not inside a try block"


@when("the lazy ui.js imports are scanned")
def scan_inbox_imports(n3ctx):
    # import('./ui.js')...catch(() => {}) — the empty-catch import pattern.
    pat = re.compile(
        r"import\(\s*['\"]\./ui\.js['\"]\s*\)[^;]*?\.catch\(\s*\(\s*\)\s*=>\s*\{\s*\}\s*\)"
    )
    n3ctx["inbox_silent_imports"] = pat.findall(n3ctx["src"])


@then("none of them end in an empty catch handler")
def inbox_no_silent_imports(n3ctx):
    # @pending: the ui.js lazy imports (L679/710/716/883/909/1194/1209) still .catch(() => {}).
    count = len(n3ctx["inbox_silent_imports"])
    assert count == 0, f"{count} ui.js lazy imports still swallow load failures"


@when("the last-seen UID write is inspected")
def inspect_inbox_write(n3ctx):
    src = n3ctx["src"]
    m = re.search(r"localStorage\.setItem\(\s*['\"]applicant-email-last-seen-uid['\"]", src)
    assert m is not None, "last-seen UID write not found"
    # The setItem sits inside an async `.then(data => { ... })` callback. The
    # synchronous `try {` in markInboxAsSeen returns before that promise resolves,
    # so it does NOT guard the write. The honest probe: inspect the immediate
    # enclosing callback body (the lines between the nearest `=> {` before the
    # write and the next `})`/`})`) for its own try/catch around the storage call.
    before = src[: m.start()]
    cb_open = before.rfind("=> {")
    after = src[m.start() :]
    cb_close = after.find("})")
    body = src[cb_open : m.start() + (cb_close if cb_close != -1 else 0)]
    n3ctx["inbox_write_guarded"] = "try" in body


@then("the localStorage write is wrapped in a try block")
def inbox_write_guarded(n3ctx):
    # @pending: the setItem sits in a .then() callback with no try/catch — a quota
    # error there is swallowed by the chained empty .catch(() => {}).
    assert n3ctx["inbox_write_guarded"], (
        "last-seen UID write is not inside a try block"
    )


# ===========================================================================
# #330 — assistant.js applicantChat.js import silently swallowed
# ===========================================================================
@given("the assistant browser module")
def given_assistant(n3ctx):
    n3ctx["src"] = _read("assistant.js")


@when("the presets fetch fallback is inspected")
def inspect_presets(n3ctx):
    # The presets fetch degrades to an empty object/array on failure.
    n3ctx["presets_fallback"] = bool(
        re.search(
            r"/api/presets['\"]\s*\)\.catch\(\s*\(\s*\)\s*=>\s*\(\s*(?:\{\}|\[\])\s*\)\s*\)",
            n3ctx["src"],
        )
    )


@then("the fetch failure falls back to an empty value rather than throwing")
def presets_fallback_ok(n3ctx):
    # GREEN: the presets fetch keeps the panel alive with an empty default.
    assert n3ctx["presets_fallback"], "presets fetch has no safe fallback"


@when("the applicant-chat dynamic import is inspected")
def inspect_applicant_chat_import(n3ctx):
    # The cited empty-catch import: import('./applicantChat.js').catch(() => {})
    n3ctx["chat_import_silent"] = bool(
        re.search(
            r"import\(\s*['\"]\./applicantChat\.js['\"]\s*\)\.catch\(\s*\(\s*\)\s*=>\s*\{\s*\}\s*\)",
            n3ctx["src"],
        )
    )


@then("its failure handler shows an error instead of being empty")
def applicant_chat_import_feedback(n3ctx):
    # @pending: line 466 still ships import('./applicantChat.js').catch(() => {}).
    assert not n3ctx["chat_import_silent"], (
        "applicantChat.js import failure is still swallowed by an empty catch"
    )


# ===========================================================================
# #331 — document.js work markers + localStorage guard
# ===========================================================================
@given("the document browser module")
def given_document(n3ctx):
    n3ctx["src"] = _read("document.js")


@when("the module is scanned for work markers")
def scan_doc_markers(n3ctx):
    n3ctx["doc_markers"] = WORK_MARKER.findall(n3ctx["src"])


@then("it contains no TODO, FIXME or HACK marker")
def doc_no_markers(n3ctx):
    # GREEN: document.js carries no unresolved work markers on this branch.
    assert n3ctx["doc_markers"] == [], (
        f"document.js still carries {len(n3ctx['doc_markers'])} work markers"
    )


@when("the visible-state persistence is inspected")
def inspect_doc_storage(n3ctx):
    src = n3ctx["src"]
    # _markDocVisibleState writes open/minimized state to localStorage.
    m = re.search(r"function _markDocVisibleState\([^)]*\)\s*\{(.*?)\n  \}", src, re.S)
    assert m is not None, "_markDocVisibleState not found"
    body = m.group(1)
    n3ctx["doc_storage_guarded"] = "try" in body and "localStorage" in body


@then("the localStorage writes are wrapped in a try block")
def doc_storage_guarded(n3ctx):
    # @pending: the open/minimize localStorage writes (L121-128) are still unguarded.
    assert n3ctx["doc_storage_guarded"], (
        "document visible-state localStorage writes are not wrapped in a try block"
    )


# ===========================================================================
# #334 — UMBRELLA: repo-wide silent-catch inventory
# ===========================================================================
# The audited module probed for "zero silent catches" — chat.js is partly fixed
# (its JSON.parse is guarded) but still ships empty catch blocks today.
_UMBRELLA_TARGET = "chat.js"
# Post-cleanup ceiling: the audit baseline is 600+ silent catches across ~70
# modules. Any meaningful cleanup of the audited modules lands well below this.
_POST_CLEANUP_CEILING = 50


def _all_silent_catches() -> dict[str, int]:
    counts: dict[str, int] = {}
    for p in sorted(JS.rglob("*.js")):
        n = _silent_catch_count(p.read_text(encoding="utf-8", errors="ignore"))
        if n:
            counts[str(p.relative_to(JS))] = n
    return counts


@given("the workspace browser modules")
def given_ws_modules(n3ctx):
    n3ctx["js_root"] = JS


@when("the silent catch blocks are counted across every module")
def count_all_silent_catches(n3ctx):
    counts = _all_silent_catches()
    n3ctx["per_file"] = counts
    n3ctx["total_silent"] = sum(counts.values())
    n3ctx["files_with_silent"] = len(counts)


@then("many modules contain many silent catch blocks")
def many_silent_catches(n3ctx):
    # GREEN: the systemic problem is real — dozens of files, hundreds of occurrences.
    assert n3ctx["files_with_silent"] >= 10, (
        f"only {n3ctx['files_with_silent']} modules have silent catches"
    )
    assert n3ctx["total_silent"] >= 100, (
        f"only {n3ctx['total_silent']} silent catches found across the tree"
    )


@when("the audited target module is scanned for silent catches")
def scan_target_module(n3ctx):
    n3ctx["target_silent"] = _silent_catch_count(_read(_UMBRELLA_TARGET))


@then("it contains no empty catch block")
def target_no_silent(n3ctx):
    # @pending: the audited target (chat.js) still ships empty catch blocks.
    assert n3ctx["target_silent"] == 0, (
        f"{_UMBRELLA_TARGET} still has {n3ctx['target_silent']} silent catch blocks"
    )


@then("the total is below the post-cleanup ceiling")
def total_under_ceiling(n3ctx):
    # @pending: the repo-wide inventory is far above the post-cleanup ceiling today.
    total = n3ctx["total_silent"]
    assert total < _POST_CLEANUP_CEILING, (
        f"{total} silent catches repo-wide; still above the {_POST_CLEANUP_CEILING} ceiling"
    )


# ===========================================================================
# #352 — cookbookRunning.js shell exec + catches + innerHTML
# ===========================================================================
@given("the cookbook running browser module")
def given_cookbook(n3ctx):
    n3ctx["src"] = _read("cookbookRunning.js")


@when("the remote-execution calls are inspected")
def inspect_shell_exec(n3ctx):
    n3ctx["shell_exec_count"] = len(re.findall(r"/api/shell/exec", n3ctx["src"]))


@then("it sends commands to the shell-exec endpoint")
def shell_exec_present(n3ctx):
    # GREEN: the module routes remote commands through /api/shell/exec (RCE surface).
    assert n3ctx["shell_exec_count"] >= 10, (
        f"only {n3ctx['shell_exec_count']} shell-exec calls found"
    )


@when("the remote SSH command builders are inspected")
def inspect_cookbook_ssh(n3ctx):
    src = n3ctx["src"]
    # The SSH command builders interpolate task.remoteHost / task.sessionId straight
    # into the command string (e.g. `ssh ${pf}${host} "powershell -Command ..."`).
    n3ctx["ssh_raw_interp"] = bool(
        re.search(r"ssh \$\{[^}]*\}\$\{(?:host|task\.remoteHost)\}", src)
    )
    # A shell-quoting helper would wrap those fields before embedding them.
    n3ctx["has_shell_quote"] = bool(
        re.search(r"shellQuote|shQuote|shellEscape|quoteArg|shlex", src)
    )


@then("the host and session id are shell-quoted rather than interpolated raw")
def cookbook_ssh_quoted(n3ctx):
    # @pending: task fields are interpolated raw with no shell-quoting helper — a
    # command-injection surface until the fields are quoted/escaped.
    assert n3ctx["ssh_raw_interp"], "expected raw SSH interpolation in the running view"
    assert n3ctx["has_shell_quote"], (
        "cookbookRunning.js interpolates host/session id into SSH commands without "
        "shell-quoting"
    )
