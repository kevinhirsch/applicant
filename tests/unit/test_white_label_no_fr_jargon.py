"""White-label guard: no FR-/NFR- requirement jargon in user-facing strings.

Binding working principle #3: the product is **Applicant**; user-facing strings use
plain language with zero ``FR-``/``NFR-`` requirement IDs. Requirement traceability
belongs in comments/docstrings (which this guard ignores), never in a message that can
reach the UI.

A string is treated as *user-facing* when it is either:

* the message of a ``raise`` (exception messages surface to the UI via the global
  error handler as the HTTP ``detail``), or
* the value of a ``detail=`` / ``message=`` keyword argument on any call
  (e.g. ``HTTPException(detail=...)``).

The CI white-label step only scans the upstream-fork *codename* denylist, so this
in-suite guard is the home of the FR-/NFR-jargon check. A leak previously reached the
front-door verbatim (e.g. the decline-feedback 422 detail and the AI-add-sensitive
rejection), which is what this test pins shut.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "src" / "applicant"
_JARGON = re.compile(r"\((?:FR|NFR)-[A-Za-z0-9-]+\)")


def _string_constants(node: ast.AST) -> list[str]:
    """Every string literal inside an expression (plain ``str`` + f-string parts)."""
    out: list[str] = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            out.append(sub.value)
    return out


def _user_facing_strings(tree: ast.AST) -> list[str]:
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Raise) and node.exc is not None:
            found.extend(_string_constants(node.exc))
        elif isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg in ("detail", "message"):
                    found.extend(_string_constants(kw.value))
    return found


def _py_files() -> list[Path]:
    return sorted(p for p in _SRC.rglob("*.py") if "__pycache__" not in p.parts)


@pytest.mark.unit
def test_no_fr_nfr_jargon_in_user_facing_messages():
    offenders: list[str] = []
    for path in _py_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for text in _user_facing_strings(tree):
            if _JARGON.search(text):
                offenders.append(f"{path.relative_to(_SRC.parents[1])}: {text!r}")
    assert not offenders, (
        "User-facing string(s) leak FR-/NFR- jargon (white-label principle #3); "
        "strip the requirement id from the message:\n  " + "\n  ".join(offenders)
    )
