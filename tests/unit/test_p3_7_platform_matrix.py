"""Regression coverage for P3-7 (Platform matrix).

The story's DoD is "amd64-only constraint documented OR multi-arch built;
Docker-on-WSL2 path tested." This is a doc-heavy story (see
``docs/platform-matrix.md``), so the code-side contract pinned here is:

1. The doc exists and actually says what it claims (amd64-only, the specific
   binary reasons, WSL2 procedure, the honest not-yet-observed label) — a
   lightweight content contract so a future edit can't quietly hollow it out.
2. It's linked from the doc index (``docs/overview.md``) and cross-linked
   from the sibling requirements/model-matrix doc (P3-2), per the "reachable
   from where deploy docs live" instruction.
3. The **documented constraint matches the code that causes it** — the
   Dockerfile's Chrome download must still be amd64-specific. If someone
   later makes the Dockerfile multi-arch without touching this doc, this
   test fails and points them at the doc that needs updating too (or, if
   multi-arch was genuinely wired up, tells them the DoD's "OR" branch has
   been taken and the doc must be revised to match).
"""

from __future__ import annotations

from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_DOC = _REPO / "docs" / "platform-matrix.md"
_DOCKERFILE = _REPO / "docker" / "Dockerfile"
_OVERVIEW = _REPO / "docs" / "overview.md"
_REQ_MATRIX = _REPO / "docs" / "requirements-and-model-matrix.md"
_INSTALL_SH = _REPO / "scripts" / "install.sh"


def test_platform_matrix_doc_exists_and_states_the_constraint():
    assert _DOC.is_file(), "docs/platform-matrix.md must exist (P3-7 DoD)."
    text = _DOC.read_text()
    # The core claim: amd64-only, with the concrete binary reasons.
    assert "amd64" in text
    assert "arm64" in text
    assert "google-chrome-stable_current_amd64.deb" in text, (
        "the doc must cite the exact Dockerfile line driving the constraint, "
        "not just assert amd64-only in the abstract"
    )
    assert "Camoufox" in text
    # WSL2 path + honest labelling, matching the P1-2/P3-1 not-yet-observed style.
    assert "WSL2" in text
    assert "procedure" in text.lower() and "not observed" in text.lower()


def test_platform_matrix_is_linked_from_the_doc_index():
    overview = _OVERVIEW.read_text()
    assert "docs/platform-matrix.md" in overview or "platform-matrix.md" in overview, (
        "docs/overview.md's doc index table must link docs/platform-matrix.md"
    )


def test_platform_matrix_is_cross_linked_from_requirements_and_model_matrix():
    req_matrix = _REQ_MATRIX.read_text()
    assert "platform-matrix.md" in req_matrix, (
        "P3-2's §5 Platform/OS constraints should point at the P3-7 doc "
        "instead of leaving it as an open question"
    )


def test_documented_constraint_matches_the_dockerfile():
    dockerfile = _DOCKERFILE.read_text()
    assert "google-chrome-stable_current_amd64.deb" in dockerfile, (
        "docs/platform-matrix.md documents an amd64-only constraint grounded "
        "in this exact line — if the Dockerfile changes to a multi-arch "
        "Chrome source, the doc (and this test) must be revisited, not left "
        "to silently drift out of sync with the code."
    )


def test_install_sh_warns_on_non_amd64_host():
    # scripts/install.sh's preflight should surface the same honest signal at
    # install time, not just in a doc nobody reads before running the script.
    # Pin the actual preflight branch (the case guard + the exact ui_warn
    # tokens the script emits), not just an incidental mention of the words —
    # a loose substring check would still pass if the warning were deleted but
    # "amd64" survived somewhere unrelated in the file.
    install_sh = _INSTALL_SH.read_text()
    # The arch dispatch that gates the warning.
    assert "x86_64|amd64)" in install_sh, (
        "install.sh preflight must branch on the host arch (case x86_64|amd64)"
    )
    # The exact warn strings the added branch emits (see the ui_warn lines).
    assert "is not x86_64/amd64 — the production image" in install_sh
    assert "(real Google Chrome + Camoufox) is amd64-only today. See" in install_sh
    assert "docs/platform-matrix.md before continuing on this host." in install_sh
