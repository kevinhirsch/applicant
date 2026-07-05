"""Regression coverage for docs/design/audits/exhaustive2/04_failure_paths.md
finding #70: the `ui_control` "highlight" action's `document.querySelector`
call used an engine/model-supplied, untrusted CSS selector with no guard of
its own — a malformed selector (e.g. unbalanced brackets/quotes) throws a
`SyntaxError` that only the *outer* `try/catch` around the whole
`handleUIControl` dispatcher caught, silently aborting the rest of the SSE
stream handler for that event (no highlight, no error surfaced, no further
`ui_control` branches for later events in the same dispatch run).

Follows the convention of ``test_applicant_backlog_dupguard.py``: every fact
is read from the actual static file content via ``pathlib`` + regex — no
browser, no DOM, no real socket.

Fix under test (``workspace/static/js/chatStream.js``, ``handleUIControl``,
the ``highlight`` branch): the ``document.querySelector(uiData.selector)``
call is now wrapped in its own local ``try/catch`` so a bad selector just
skips that one highlight action (optionally logging a warning) instead of
throwing past the local ``if (target)`` guard and being caught by the outer
handler catch, which — before this fix — also meant any code *after* the
`querySelector` call inside the branch never ran.

Each assertion below was verified failing by hand (temporarily reverting the
local try/catch, restoring the earlier bare
``var target = document.querySelector(uiData.selector);``, rerunning to see a
real ``AssertionError``, then restoring the fix) before this file was landed.
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
CHATSTREAM_JS = REPO_ROOT / "workspace" / "static" / "js" / "chatStream.js"


def _read() -> str:
    return CHATSTREAM_JS.read_text(encoding="utf-8")


def _top_level_fn(src: str, name: str) -> str:
    """Extract a top-level (unindented) `function name(...) { ... }` body.

    Same convention as ``test_applicant_backlog_dupguard.py``: the function's
    own closing brace is the first line consisting of a bare "}" with no
    leading whitespace.
    """
    m = re.search(rf"function {re.escape(name)}\([^)]*\)\s*\{{(.*?)\n\}}", src, re.S)
    assert m, f"expected a top-level function {name}(...) in the source"
    return m.group(1)


def _highlight_branch(body: str) -> str:
    """Slice out just the `highlight` else-if branch of handleUIControl,
    stopping at the next `} else if` / `}` that closes the branch."""
    m = re.search(
        r"else if \(uiEvent === 'highlight'.*?\{(.*?)\n\s*\} else if \(uiEvent === 'clear_highlight'",
        body,
        re.S,
    )
    assert m, "expected to find the 'highlight' ui_control branch"
    return m.group(1)


# ── the querySelector call is now individually guarded ──────────────────────


def test_highlight_queryselector_is_wrapped_in_its_own_try_catch():
    branch = _highlight_branch(_top_level_fn(_read(), "handleUIControl"))
    m = re.search(
        r"try\s*\{[^}]*document\.querySelector\(uiData\.selector\)[^}]*\}\s*catch\s*\([A-Za-z_$][\w$]*\)\s*\{",
        branch,
        re.S,
    )
    assert m, (
        "expected document.querySelector(uiData.selector) to be wrapped in "
        "its own local try/catch inside the 'highlight' branch, so a bad "
        "selector is handled locally rather than relying on the outer "
        "handleUIControl catch"
    )


def test_highlight_target_defaults_to_null_before_the_guarded_lookup():
    """The guard must leave `target` falsy (not throw / leave it undefined in
    a way that breaks the `if (target)` check below) when the selector is bad."""
    branch = _highlight_branch(_top_level_fn(_read(), "handleUIControl"))
    assert re.search(r"var target\s*=\s*null\s*;", branch), (
        "expected 'target' to be explicitly initialized to null before the "
        "guarded querySelector lookup, so a caught SyntaxError leaves it "
        "safely falsy for the 'if (target)' check"
    )


def test_highlight_still_applies_target_when_selector_is_valid():
    """Guarding the call must not change behavior for a valid selector: the
    existing highlight/scroll/label logic must still run against `target`."""
    branch = _highlight_branch(_top_level_fn(_read(), "handleUIControl"))
    assert "target.classList.add('applicant-highlight')" in branch
    assert "target.scrollIntoView(" in branch


def test_outer_handler_catch_is_still_present_as_a_backstop():
    """The outer try/catch around the whole dispatcher should remain (defense
    in depth) — this fix narrows the blast radius, it doesn't remove the
    outer safety net."""
    src = _read()
    assert "ui_control handler error" in src
