#!/usr/bin/env python
"""Lightweight, dependency-free secret scan for CI (P1-0, issue #651).

Runs as its own CI step (no external action/binary download — a self-hosted
runner may have no outbound network, and the hosted fallback runner shouldn't
need one either) over every ``git``-tracked file, flagging text that looks like
a real, live credential: cloud/provider API keys, GitHub/Slack/npm tokens, and
PEM private-key blocks.

Deliberately narrow (recall over precision would just retrain everyone to
ignore CI): patterns require an actual key-shaped value (a real minimum
length), so they do NOT fire on:
  * this repo's own credential-*shaped* regexes/denylists (e.g.
    ``src/applicant/observability/logging.py``'s redaction pattern,
    ``frontend/static/js/censor.js``'s censor table) — those match the
    STRUCTURE of a key, they don't embed one;
  * short illustrative prefixes in docs/usage strings (``sk-ant-...``,
    ``sk-or-...``) — the placeholder ``...`` fails the length check;
  * the seed-data invariant test (``tests/unit/test_seed_demo_p0_2.py``),
    which asserts *absence* of secrets using the same prefixes as bare
    literals (``"sk-"``, ``"ghp_"``) with no key-length payload.

Exit code 1 (with every match printed) fails the CI job; exit 0 otherwise.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Paths this scan does not need to look inside: lockfiles (huge, machine-
# generated, never hand-authored so unlikely to gain a credential this scan
# would need to catch), and node_modules if ever vendored transiently.
_EXCLUDED_DIR_PARTS = {"node_modules", ".git"}
_EXCLUDED_SUFFIXES = {".lock"}
_EXCLUDED_NAMES = {"uv.lock", "package-lock.json"}

# (label, compiled pattern). Each requires an actual key-shaped payload, not
# just a provider prefix, so illustrative snippets and structural
# redaction/censor regexes elsewhere in the repo don't trip this.
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("OpenAI/OpenRouter/Anthropic-style secret key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("GitHub personal/OAuth/app token", re.compile(r"\bgh[oprsu]_[A-Za-z0-9]{36,}\b")),
    ("GitHub fine-grained PAT", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("GitLab personal access token", re.compile(r"\bglpat-[A-Za-z0-9\-_]{20,}\b")),
    ("Slack token", re.compile(r"\bxox[bpras]-[A-Za-z0-9\-]{10,}\b")),
    ("npm token", re.compile(r"\bnpm_[A-Za-z0-9]{36,}\b")),
    ("AWS access key id", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("PEM private key block", re.compile(r"-----BEGIN\s[\w\s]*PRIVATE KEY-----")),
)

# Files that legitimately embed these patterns as detectors/denylists (i.e.
# structural regex source, not a literal secret). Kept short and reasoned —
# mirrors the white-label denylist's own explicit-exclusion discipline.
_ALLOWED_FILES = {
    "src/applicant/observability/logging.py",
    "frontend/static/js/censor.js",
    "workspace/static/js/censor.js",
    "scripts/ci/secret_scan.py",
    # Fixture-shaped, fake key exercising the redaction/censor logic itself —
    # not a real, live credential.
    "tests/unit/test_observability.py",
}


def _tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in out.stdout.splitlines() if line.strip()]


def _should_scan(rel_path: str) -> bool:
    if rel_path in _ALLOWED_FILES:
        return False
    p = Path(rel_path)
    if p.name in _EXCLUDED_NAMES:
        return False
    if p.suffix in _EXCLUDED_SUFFIXES:
        return False
    if _EXCLUDED_DIR_PARTS & set(p.parts):
        return False
    return True


def scan() -> list[str]:
    findings: list[str] = []
    for rel_path in _tracked_files():
        if not _should_scan(rel_path):
            continue
        full = REPO_ROOT / rel_path
        try:
            text = full.read_text(encoding="utf-8", errors="ignore")
        except (OSError, UnicodeDecodeError):
            continue
        for label, pattern in _PATTERNS:
            for match in pattern.finditer(text):
                line_no = text.count("\n", 0, match.start()) + 1
                findings.append(f"{rel_path}:{line_no}: {label}: {match.group(0)[:12]}…")
    return findings


def main() -> int:
    findings = scan()
    if findings:
        print("Secret scan found possible committed credentials:\n", file=sys.stderr)
        for f in findings:
            print(f"  {f}", file=sys.stderr)
        print(
            "\nIf this is a genuine false positive (a detector/denylist regex, not a "
            "real key), add the file to _ALLOWED_FILES in scripts/ci/secret_scan.py "
            "with a one-line reason.",
            file=sys.stderr,
        )
        return 1
    print("secret scan clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
