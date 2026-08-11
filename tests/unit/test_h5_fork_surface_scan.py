"""H5 — Honesty: overclaim-denylist scan over fork user-facing surfaces (AZ5-3 slice).

Sweeps the same denylist as test_h5_calibrated_copy.py but targets the fork's
user-facing surfaces: every *.html under a0-applicant/webui/, the agent
guidance markdown at a0-applicant/prompts/agent_guidance.md, every persona
overlay *.md under a0-applicant/agents/applicant/prompts/, and the per-surface
help copy in a0-applicant/config/help_content.yaml.

HTML files are pre-processed: HTML comments are removed, then JS-style comments
(// and /* */) are stripped so that inline <script> blocks and engineering
comments do not trigger false positives.
"""

from __future__ import annotations

import pathlib
import re

import yaml

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_FORK_WEBUI = _REPO_ROOT / "a0-applicant" / "webui"
_FORK_GUIDANCE = _REPO_ROOT / "a0-applicant" / "prompts" / "agent_guidance.md"
_FORK_PERSONA_OVERLAYS = _REPO_ROOT / "a0-applicant" / "agents" / "applicant" / "prompts"
_FORK_HELP_CONTENT = _REPO_ROOT / "a0-applicant" / "config" / "help_content.yaml"

# ── The denylist (verbatim copy from test_h5_calibrated_copy.py) ─────────────

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
    r"\b(?:no|not|never|nothing|none|isn|aren|don|doesn|won|cannot|can['']t|without)\b",
    re.IGNORECASE,
)


def _is_negated(text: str, start: int) -> bool:
    return bool(_NEGATION.search(text[max(0, start - _NEGATION_WINDOW):start]))


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


def _find_overclaims(text: str, where: str) -> list[str]:
    hits: list[str] = []
    for name, pattern in OVERCLAIM_PATTERNS:
        for m in pattern.finditer(text):
            if _is_negated(text, m.start()):
                continue
            line_no = text.count("\n", 0, m.start()) + 1
            hits.append(f"{where}:{line_no}: [{name}] {m.group(0)!r}")
    return hits


def _iter_yaml_strings(node: object) -> list[tuple[str, str]]:
    """Yield (text, where) for every scalar string value in a YAML document."""
    out: list[tuple[str, str]] = []
    if isinstance(node, str):
        out.append((node, "help_content.yaml"))
    elif isinstance(node, dict):
        for key, value in node.items():
            key_label = f"help_content.yaml[{key}]"
            if isinstance(value, str):
                out.append((value, key_label))
            elif isinstance(value, list):
                for i, item in enumerate(value):
                    if isinstance(item, str):
                        out.append((item, f"{key_label}[{i}]"))
                    else:
                        out.extend(
                            (text, f"{key_label}[{i}]")
                            for text, _ in _iter_yaml_strings(item)
                        )
            elif isinstance(value, (dict, list)):
                out.extend((text, key_label) for text, _ in _iter_yaml_strings(value))
    elif isinstance(node, list):
        for i, item in enumerate(node):
            if isinstance(item, str):
                out.append((item, f"help_content.yaml[{i}]"))
            else:
                out.extend((text, f"help_content.yaml[{i}]") for text, _ in _iter_yaml_strings(item))
    return out


# ── Tests ────────────────────────────────────────────────────────────────────

def test_fork_surfaces_exist() -> None:
    """Guard: the scan targets must exist so the test can't silently pass on an empty glob."""
    html_files = sorted(_FORK_WEBUI.glob("*.html"))
    assert html_files, "a0-applicant/webui/ has no *.html files — glob path may have changed"
    assert _FORK_GUIDANCE.exists(), "a0-applicant/prompts/agent_guidance.md not found — path may have changed"
    persona_files = sorted(_FORK_PERSONA_OVERLAYS.glob("*.md"))
    assert persona_files, "a0-applicant/agents/applicant/prompts/ has no *.md files — glob path may have changed"
    assert _FORK_HELP_CONTENT.exists(), (
        "a0-applicant/config/help_content.yaml not found — path may have changed"
    )


def test_no_overclaims_in_fork_surfaces() -> None:
    """Scan all fork webui HTML, agent_guidance.md, and persona overlays for overclaim patterns."""
    hits: list[str] = []

    # Scan HTML files: strip HTML comments, then JS comments
    for path in sorted(_FORK_WEBUI.glob("*.html")):
        raw = path.read_text(encoding="utf-8")
        text = re.sub(r"<!--.*?-->", "", raw, flags=re.S)
        text = _strip_js_comments(text)
        hits.extend(_find_overclaims(text, path.name))

    # Scan agent guidance markdown: raw text only
    if _FORK_GUIDANCE.exists():
        text = _FORK_GUIDANCE.read_text(encoding="utf-8")
        hits.extend(_find_overclaims(text, "agent_guidance.md"))

    # Scan persona overlay markdown: raw text only
    for path in sorted(_FORK_PERSONA_OVERLAYS.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        hits.extend(_find_overclaims(text, path.name))

    # Scan help_content.yaml: every scalar string value (title, steps, prerequisites)
    help_doc = yaml.safe_load(_FORK_HELP_CONTENT.read_text(encoding="utf-8"))
    for text, where in _iter_yaml_strings(help_doc):
        hits.extend(_find_overclaims(text, where))

    assert not hits, (
        "Overclaiming copy in fork surfaces (H5):\n" + "\n".join(hits)
    )
