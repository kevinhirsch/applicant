#!/usr/bin/env python
"""Release-version consistency check (P3-5, release engineering).

There are three places the current version is recorded, and they must never
drift apart:

  * ``VERSION``                        — the single source of truth a release
                                          tag / the release workflow reads.
  * ``pyproject.toml``'s ``[project].version``
  * ``src/applicant/version.py``'s ``__version__`` — what the running app
    actually reports (FastAPI ``app.version``, ``/healthz``, and now the
    front-door health panel, see ``src/applicant/app/routers/health.py``).

A mismatch here means "the thing we tag" and "the thing that's actually
running" have silently diverged — exactly the kind of drift that makes a
release note a lie. This also checks that the version is valid semver and
that ``CHANGELOG.md`` (Keep a Changelog format) carries a heading for it,
so bumping the version without writing down what changed fails loudly
instead of shipping an undocumented release.

Run directly: ``python3 scripts/ci/check_release_version.py``
Also wrapped as a hermetic pytest in ``tests/unit/test_release_engineering.py``
so it's part of the default (non-integration) suite, not just an extra CI step.

Exit code 1 (with the mismatch printed) on any inconsistency; exit 0 otherwise.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Full semver: MAJOR.MINOR.PATCH with an optional -prerelease suffix (matches
# the tag-shape check in .github/workflows/release.yml).
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$")


def _read_version_file() -> str:
    return (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()


def _read_pyproject_version() -> str:
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'(?m)^version\s*=\s*"([^"]+)"', text)
    if not match:
        raise ValueError("pyproject.toml has no [project].version = \"...\" line")
    return match.group(1)


def _read_module_version() -> str:
    text = (REPO_ROOT / "src" / "applicant" / "version.py").read_text(encoding="utf-8")
    match = re.search(r'(?m)^__version__\s*=\s*"([^"]+)"', text)
    if not match:
        raise ValueError('src/applicant/version.py has no __version__ = "..." line')
    return match.group(1)


def _changelog_has_heading_for(version: str) -> bool:
    text = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    # Keep a Changelog heading shape: "## [X.Y.Z]" (date/link suffix allowed).
    return re.search(rf"^##\s*\[{re.escape(version)}\]", text, re.MULTILINE) is not None


def check() -> list[str]:
    problems: list[str] = []

    try:
        version_file = _read_version_file()
    except OSError as exc:
        return [f"Cannot read VERSION: {exc}"]

    if not _SEMVER_RE.match(version_file):
        problems.append(
            f"VERSION ({version_file!r}) is not valid semver (MAJOR.MINOR.PATCH[-prerelease])"
        )

    try:
        pyproject_version = _read_pyproject_version()
    except (OSError, ValueError) as exc:
        problems.append(str(exc))
        pyproject_version = None

    try:
        module_version = _read_module_version()
    except (OSError, ValueError) as exc:
        problems.append(str(exc))
        module_version = None

    if pyproject_version is not None and pyproject_version != version_file:
        problems.append(
            f"pyproject.toml version ({pyproject_version!r}) != VERSION ({version_file!r})"
        )
    if module_version is not None and module_version != version_file:
        problems.append(
            f"src/applicant/version.py __version__ ({module_version!r}) != VERSION ({version_file!r})"
        )

    try:
        if not _changelog_has_heading_for(version_file):
            problems.append(
                f"CHANGELOG.md has no '## [{version_file}]' heading — add a release entry "
                "(Keep a Changelog format) when bumping VERSION."
            )
    except OSError as exc:
        problems.append(f"Cannot read CHANGELOG.md: {exc}")

    return problems


def main() -> int:
    problems = check()
    if problems:
        print("Release-version consistency check failed:\n", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        print(
            "\nBump VERSION, pyproject.toml's [project].version, and "
            "src/applicant/version.py's __version__ together, and add a "
            "CHANGELOG.md entry — see docs/release-process.md.",
            file=sys.stderr,
        )
        return 1
    print(f"release-version consistency clean (VERSION={_read_version_file()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
