"""H5 — Honesty: calibrated copy (road-to-market Phase 1.5).

Product copy must never overclaim: no guarantees of outcomes, no implied
checks that did not run, no capability promises stated as unconditional when
the capability depends on runtime state (docs/backlog/road-to-market.md, H5).
Trust breaks at the words layer, so this file does two jobs:

1. **The sweep, pinned** — a denylist of overclaim phrase patterns is run
   against every user-facing front-door surface (the ``applicant*.js``
   modules + ``entities.js``, the public ``landing.html``, and the string
   literals of the ``routes/applicant_*_routes.py`` proxies). Comments are
   stripped (JS + HTML) and, for Python, only string literals are scanned —
   engineering commentary may legitimately discuss "guarantees"; shipped copy
   may not. A negation window keeps honest *disclaimers* ("never a
   guarantee", "no setup is ever guaranteed to be undetectable") passing —
   those are exactly the calibrated copy this story protects.

2. **Specific calibrations, pinned** — the individual overclaims the H5
   sweep found and fixed must not regress:
   * the Portal "While you were away" recap said "reviewed N postings" for
     the ``discovered`` stat (discovery *finds*; "review" is the human's
     step in this product) and "pre-filled N" for ``pipelines_started``
     (started, not necessarily finished);
   * the wizard's résumé-step tooltip promised "I build a polished version"
     unconditionally, even though rendering depends on document tools being
     present in the running install (the H5 DoD's own example).

Convention: static-source assertions via ``pathlib`` + regex, mirroring
``test_applicant_copy_portal_lens02.py`` and the other copy-lens files.
"""

from __future__ import annotations

import ast
import pathlib
import re

_WORKSPACE = pathlib.Path(__file__).resolve().parent.parent  # workspace/
_JS_DIR = _WORKSPACE / "static" / "js"
_LANDING = _WORKSPACE / "static" / "landing.html"
_ROUTES_DIR = _WORKSPACE / "routes"

# ── The denylist ─────────────────────────────────────────────────────────────
# Each entry: (name, compiled pattern). Matched case-insensitively against
# comment-stripped user-facing source. A match is allowed only when a negation
# appears shortly before it (an honest disclaimer), checked by _is_negated.

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

# A negation within this many characters before the match makes it an honest
# disclaimer rather than a claim ("… is NEVER a guarantee", "NO setup is ever
# guaranteed to be undetectable").
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


# ── Comment stripping / literal extraction ───────────────────────────────────

def _strip_js_comments(src: str) -> str:
    """Drop // and /* */ comments while preserving string/template contents."""
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
        # Inside a string/template literal.
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


# ── 1. The sweep ─────────────────────────────────────────────────────────────

def _applicant_js_files() -> list[pathlib.Path]:
    files = sorted(_JS_DIR.glob("applicant*.js"))
    files.append(_JS_DIR / "entities.js")  # hosts the applicant profile section
    return [f for f in files if f.is_file()]


def test_the_sweep_finds_files_to_sweep():
    """Guard the sweep itself: an empty scan must fail loudly, not pass green."""
    assert len(_applicant_js_files()) > 10, "applicant JS surface list looks wrong"
    assert _LANDING.is_file(), "landing.html moved — update this sweep"
    assert list(_ROUTES_DIR.glob("applicant_*_routes.py")), "proxy route files moved"


def test_no_overclaims_in_applicant_front_door_js():
    hits: list[str] = []
    for path in _applicant_js_files():
        text = _strip_js_comments(path.read_text(encoding="utf-8"))
        hits.extend(_find_overclaims(text, path.name))
    assert not hits, "Overclaiming copy in front-door JS (H5):\n" + "\n".join(hits)


def test_no_overclaims_on_the_landing_page():
    text = re.sub(r"<!--.*?-->", "", _LANDING.read_text(encoding="utf-8"), flags=re.S)
    hits = _find_overclaims(text, _LANDING.name)
    assert not hits, "Overclaiming copy on landing.html (H5):\n" + "\n".join(hits)


def test_no_overclaims_in_proxy_route_strings():
    hits: list[str] = []
    for path in sorted(_ROUTES_DIR.glob("applicant_*_routes.py")):
        for literal, label in _python_string_literals(
            path.read_text(encoding="utf-8"), path.name
        ):
            for hit in _find_overclaims(literal, label):
                hits.append(hit)
    assert not hits, "Overclaiming copy in proxy routes (H5):\n" + "\n".join(hits)


def test_the_negation_window_keeps_honest_disclaimers_passing():
    """The sweep must not flag calibrated disclaimers — they are the point."""
    disclaimer = (
        "the honest, best-effort picture; no anti-detection setup is ever "
        "guaranteed to be undetectable."
    )
    assert _find_overclaims(disclaimer, "x") == []
    # …while the same words WITHOUT the negation are flagged.
    claim = "our anti-detection setup is guaranteed to be undetectable."
    assert len(_find_overclaims(claim, "x")) >= 1


# ── 2. The specific calibrations ────────────────────────────────────────────

def _portal_src() -> str:
    return (_JS_DIR / "applicantPortal.js").read_text(encoding="utf-8")


def _onboarding_src() -> str:
    return (_JS_DIR / "applicantOnboarding.js").read_text(encoding="utf-8")


def test_recap_says_found_not_reviewed_for_the_discovered_stat():
    """`discovered` counts postings discovery FOUND; nothing was 'reviewed'."""
    src = _portal_src()
    assert "found ${t.discovered} posting" in src
    assert "reviewed ${t.discovered}" not in src


def test_recap_says_started_prefilling_for_pipelines_started():
    """`pipelines_started` counts pre-fills STARTED — completion isn't known."""
    src = _portal_src()
    assert "started pre-filling ${t.prefilled}" in src
    assert "`pre-filled ${t.prefilled}`" not in src


def test_wizard_resume_tooltip_conditions_the_polished_version_promise():
    """The polished-preview promise is conditional on the install's document
    tools (the H5 DoD's TeX example) and names the honest fallback."""
    src = _onboarding_src()
    assert "if this install can render documents" in src
    assert "I say so and keep using your original file" in src
