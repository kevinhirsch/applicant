"""H5 — Honesty: calibrated copy (road-to-market Phase 1.5) — engine surfaces.

Product copy must never overclaim: no guarantees of outcomes, no implied
checks that did not run, no capability promises stated as unconditional when
the capability depends on runtime state (docs/backlog/road-to-market.md, H5).

This is the engine-side half of the H5 pin (the front-door half lives in
``workspace/tests/test_applicant_calibrated_copy.py`` — the two lanes run
under different pytest configs, so each carries its own self-contained copy
of the checker). It sweeps a denylist of overclaim phrase patterns against:

* the engine's own built-in shell (``frontend/static/applicant`` — HTML + JS,
  comments stripped), and
* every **string literal** in ``src/applicant`` (docstrings and comments are
  engineering commentary and may legitimately discuss "guarantees"; string
  literals are what can reach a user).

A negation window keeps honest *disclaimers* passing ("Anti-detection is
best-effort, never a guarantee" — ``adapters/browser/stealth.py``) — those
are exactly the calibrated copy this story protects.

It also pins the H5 DoD's own example the other way around: when TeX /
LibreOffice are absent, the rendered-preview copy must SAY the tools aren't
available (absence of a capability never renders as the capability).
"""

from __future__ import annotations

import ast
import pathlib
import re

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_ENGINE_SHELL = _REPO_ROOT / "frontend" / "static" / "applicant"
_ENGINE_SRC = _REPO_ROOT / "src" / "applicant"

# ── The denylist (same shape as the front-door lane's copy) ──────────────────

OVERCLAIM_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "guaranteed-outcome",
        re.compile(
            r"\bguaranteed?\s+(?:to\b|you\b|success\b|an?\s+(?:interview|job|offer|response)\b)",
            re.IGNORECASE,
        ),
    ),
    ("first-person-guarantee", re.compile(r"\b(?:we|i)\s+guarantee\b", re.IGNORECASE)),
    (
        "percent-certainty",
        re.compile(
            r"\b100%\s*(?:accurate|accuracy|safe|secure|success|successful|correct|reliable|effective)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "absolute-reliability",
        re.compile(
            r"\b(?:always\s+works|never\s+fails|error[-\s]free|flawless|foolproof|risk[-\s]free|zero\s+risk)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "hiring-outcome-promise",
        re.compile(
            r"\b(?:gets?\s+you\s+hired|lands?\s+(?:you\s+)?the\s+job|gets?\s+you\s+an\s+interview)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "coverage-overclaim",
        re.compile(
            r"\b(?:every\s+job\s+board|all\s+job\s+boards|the\s+entire\s+web|the\s+whole\s+web|full\s+coverage|complete\s+coverage)\b",
            re.IGNORECASE,
        ),
    ),
    ("stealth-overclaim", re.compile(r"\bundetectable\b", re.IGNORECASE)),
    (
        "beauty-overclaim",
        re.compile(
            r"\bbeautifully\b|\bbeautiful\s+(?:pdf|résumé|resume|document)\b",
            re.IGNORECASE,
        ),
    ),
    ("automation-overclaim", re.compile(r"\bfully\s+automat(?:ed|ic)\b", re.IGNORECASE)),
]

_NEGATION_WINDOW = 80
_NEGATION = re.compile(
    r"\b(?:no|not|never|nothing|none|isn|aren|don|doesn|won|cannot|can['’]t|without)\b",
    re.IGNORECASE,
)


def _is_negated(text: str, start: int) -> bool:
    return bool(_NEGATION.search(text[max(0, start - _NEGATION_WINDOW):start]))


def _find_overclaims(text: str, where: str) -> list[str]:
    hits = []
    for name, pattern in OVERCLAIM_PATTERNS:
        for m in pattern.finditer(text):
            if _is_negated(text, m.start()):
                continue
            line_no = text.count("\n", 0, m.start()) + 1
            hits.append(f"{where}:{line_no}: [{name}] {m.group(0)!r}")
    return hits


def _strip_js_comments(src: str) -> str:
    out: list[str] = []
    i, n = 0, len(src)
    state: str | None = None  # None | quote char | 'line' | 'block'
    while i < n:
        c = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
        if state is None:
            if c == "/" and nxt == "/":
                state = "line"
                i += 2
                continue
            if c == "/" and nxt == "*":
                state = "block"
                i += 2
                continue
            if c in ("'", '"', "`"):
                state = c
            out.append(c)
            i += 1
            continue
        if state == "line":
            if c == "\n":
                state = None
                out.append(c)
            i += 1
            continue
        if state == "block":
            if c == "*" and nxt == "/":
                state = None
                i += 2
                continue
            if c == "\n":
                out.append(c)
            i += 1
            continue
        if c == "\\":
            out.append(c)
            if i + 1 < n:
                out.append(nxt)
            i += 2
            continue
        if c == state:
            state = None
        out.append(c)
        i += 1
    return "".join(out)


def _python_string_literals(src: str, where: str) -> list[tuple[str, str]]:
    """(literal, label) pairs for non-docstring string constants in a module."""
    tree = ast.parse(src)
    docstring_ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                if isinstance(body[0].value.value, str):
                    docstring_ids.add(id(body[0].value))
    literals: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstring_ids
        ):
            literals.append((node.value, f"{where}:{node.lineno}"))
    return literals


# ── The sweep ────────────────────────────────────────────────────────────────

def test_the_sweep_finds_files_to_sweep():
    """Guard the sweep itself: an empty scan must fail loudly, not pass green."""
    assert list(_ENGINE_SHELL.glob("*.html")), "engine shell HTML moved — update sweep"
    assert list(_ENGINE_SHELL.glob("js/*.js")), "engine shell JS moved — update sweep"
    assert len(list(_ENGINE_SRC.rglob("*.py"))) > 50, "engine source tree looks wrong"


def test_no_overclaims_in_the_engine_shell():
    hits: list[str] = []
    for path in sorted(_ENGINE_SHELL.glob("*.html")):
        text = re.sub(r"<!--.*?-->", "", path.read_text(encoding="utf-8"), flags=re.S)
        hits.extend(_find_overclaims(text, path.name))
    for path in sorted(_ENGINE_SHELL.glob("js/*.js")):
        text = _strip_js_comments(path.read_text(encoding="utf-8"))
        hits.extend(_find_overclaims(text, f"js/{path.name}"))
    assert not hits, "Overclaiming copy in the engine shell (H5):\n" + "\n".join(hits)


def test_no_overclaims_in_engine_string_literals():
    hits: list[str] = []
    for path in sorted(_ENGINE_SRC.rglob("*.py")):
        rel = path.relative_to(_ENGINE_SRC).as_posix()
        for literal, label in _python_string_literals(
            path.read_text(encoding="utf-8"), rel
        ):
            hits.extend(_find_overclaims(literal, label))
    assert not hits, "Overclaiming copy in engine string literals (H5):\n" + "\n".join(hits)


def test_the_negation_window_keeps_honest_disclaimers_passing():
    """The sweep must not flag calibrated disclaimers — they are the point."""
    disclaimer = "Anti-detection is best-effort, never a guarantee — it is not guaranteed to be undetectable."
    assert _find_overclaims(disclaimer, "x") == []
    claim = "our fingerprinting is guaranteed to be undetectable."
    assert len(_find_overclaims(claim, "x")) >= 1


# ── The DoD's TeX example, pinned the other way around ───────────────────────

def test_absent_document_tools_copy_says_so_in_both_render_paths():
    """When TeX / LibreOffice are missing, the preview copy must NAME the
    degradation (H5 + H2): the absence of the polished-PDF capability never
    renders as the capability."""
    for adapter in ("latex_tailor.py", "docx_tailor.py"):
        src = (_ENGINE_SRC / "adapters" / "resume_tailoring" / adapter).read_text(
            encoding="utf-8"
        )
        assert "The document tools needed to build the polished PDF aren't available" in src, (
            f"{adapter}: the missing-tools preview note was reworded or removed — "
            "the absent-capability copy must keep saying the tools are absent"
        )
