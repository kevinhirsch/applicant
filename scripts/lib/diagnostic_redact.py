#!/usr/bin/env python3
"""Redaction core for the diagnostic bundle (P5-1, "Support machinery").

``scripts/diagnostic-bundle.sh`` pipes every piece of text it collects (the
deploy ``.env``, per-service ``docker compose logs`` output, health-endpoint
bodies) through this module before anything is written to disk or archived.
Two layers, mirroring ``src/applicant/observability/logging.py``'s own
two-layer approach (key-name redaction AND value-based redaction) so a secret
is still caught even under a key name nobody anticipated:

1. **Key-name denylist** — a ``KEY=VALUE`` line (the shape of a ``.env`` file,
   and also common in structured log output) whose key looks secret-bearing is
   fully redacted, keeping the key name (useful context for support: "yes, an
   LLM key is set") but never its value.
2. **Value-based scrubbing** — applied to every value regardless of key name
   (and to any line that isn't ``KEY=VALUE`` at all, e.g. free-text log
   prose): provider API keys, GitHub/GitLab/Slack/npm tokens, AWS access key
   ids, PEM private-key blocks, inline ``password=...``-style assignments, and
   URL userinfo credentials (``scheme://user:pass@host``) are masked wherever
   they appear, so a secret embedded in an innocuously-named field or a plain
   log message is still caught.

This is deliberately dependency-free (stdlib only) so it runs on a bare deploy
host with no ``uv``/venv — ``scripts/diagnostic-bundle.sh`` invokes it as
``python3 scripts/lib/diagnostic_redact.py < input > output``.

The redaction here is NOT caller-configurable: there is no flag to skip it and
no key a caller can pass to opt a value back into the plaintext output (CLAUDE.md
principle #5-server — redaction must be enforced in code, never trusted from a
caller). The only inputs are stdin and the fixed pattern tables below.
"""

from __future__ import annotations

import re
import sys

REDACTED = "***REDACTED***"

# --- key-name denylist -------------------------------------------------------

#: Case-insensitive SUBSTRING match against the key of a ``KEY=VALUE`` line.
#: Deliberately broad (over-redacting a benign key is harmless; under-redacting
#: a real secret is not) — this is why "key" alone is not here (it would eat
#: unrelated identifiers like a "primary_key" column name), but every actual
#: secret-shaped suffix Applicant's own config uses IS covered: POSTGRES_PASSWORD,
#: APPLICANT_INTERNAL_TOKEN, SEARXNG_SECRET, LLM_API_KEY, CAPTCHA_API_KEY,
#: PROXMOX_TOKEN_ID, PROXMOX_RDP_PASSWORD, etc. (see src/applicant/app/config.py).
_SECRET_KEY_SUBSTRINGS: tuple[str, ...] = (
    "password",
    "passwd",
    "pwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "private_key",
    "credential",
    "dsn",
)

#: Exact keys that don't contain any of the substrings above but are still a
#: full secret-bearing value (a connection string, not a key literally named
#: "...secret...").
_SECRET_KEY_EXACT: frozenset[str] = frozenset(
    {
        "database_url",
        "ui_database_url",
    }
)

_ENV_LINE_RE = re.compile(r"^(\s*(?:export\s+)?)([A-Za-z_][A-Za-z0-9_]*)(\s*=\s*)(.*)$")


def _is_secret_key(key: str) -> bool:
    k = key.strip().lower()
    if k in _SECRET_KEY_EXACT:
        return True
    return any(s in k for s in _SECRET_KEY_SUBSTRINGS)


# --- value-based patterns -----------------------------------------------------

#: Patterns whose ENTIRE match is replaced with ``REDACTED`` (no prefix to keep).
_MASK_WHOLE: tuple[re.Pattern[str], ...] = (
    # JWT: three base64url segments separated by dots.
    re.compile(r"\beyJ[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\b"),
    # OpenAI/OpenRouter/Anthropic-style secret keys (sk-..., sk-or-v1-..., sk-ant-...).
    re.compile(r"\bsk-[A-Za-z0-9_-]{19,}[A-Za-z0-9]\b"),
    re.compile(r"\bgh[oprsu]_[A-Za-z0-9]{36,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bglpat-[A-Za-z0-9\-_]{20,}\b"),
    re.compile(r"\bxox[bpras]-[A-Za-z0-9\-]{10,}\b"),
    re.compile(r"\bnpm_[A-Za-z0-9]{36,}\b"),
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    # password=... / token: ... inline in free-text (e.g. a log message). NO
    # leading \b: a prefixed key like POSTGRES_PASSWORD=... has no word
    # boundary between "_" and "PASSWORD" (both are \w), so a leading \b would
    # silently miss every *_PASSWORD/*_TOKEN/*_SECRET-shaped assignment embedded
    # in a free-text log line (only bare "password=..." would be caught) --
    # this was caught by the end-to-end fake-docker log-scrubbing test.
    re.compile(r"(?i)(?:password|passwd|pwd|secret|token|api_key|apikey|private_key)\s*[=:]\s*\S{4,}"),
)

#: Patterns where GROUP 1 (a harmless, useful prefix) is kept and everything
#: after it is replaced with ``REDACTED``.
_MASK_KEEP_PREFIX: tuple[re.Pattern[str], ...] = (
    # URL userinfo: scheme://user:pass@host -> scheme://***REDACTED***@host
    re.compile(r"([A-Za-z][A-Za-z0-9+.\-]*://)[^/\s:@]+:[^/\s@]+@"),
    # Discord/Slack-style webhook URLs embed a bearer token in the path itself.
    re.compile(r"(https://discord(?:app)?\.com/api/webhooks/\d+/)[A-Za-z0-9_-]+"),
)

#: A PEM block spans MULTIPLE lines, so it cannot be caught by the per-line
#: patterns above (``redact_text`` processes line-by-line so it can preserve
#: key-name-vs-value handling per line). This is applied to the WHOLE text
#: before line-splitting, in ``redact_text``.
_MULTILINE_WHOLE: tuple[re.Pattern[str], ...] = (
    re.compile(r"-----BEGIN\s[\w\s]*PRIVATE KEY-----[\s\S]*?-----END\s[\w\s]*PRIVATE KEY-----"),
)


def redact_value_patterns(text: str) -> str:
    """Mask secret-shaped substrings anywhere in free text (single line or not)."""
    if not text:
        return text
    out = text
    for pat in _MASK_WHOLE:
        out = pat.sub(REDACTED, out)
    for pat in _MASK_KEEP_PREFIX:
        out = pat.sub(lambda m: m.group(1) + REDACTED, out)
    return out


def redact_line(line: str) -> str:
    """Redact a single line (``KEY=VALUE`` shape, or free text)."""
    m = _ENV_LINE_RE.match(line)
    if m:
        lead, key, eq, value = m.groups()
        if _is_secret_key(key):
            return f"{lead}{key}{eq}{REDACTED}"
        return f"{lead}{key}{eq}{redact_value_patterns(value)}"
    return redact_value_patterns(line)


def redact_text(text: str) -> str:
    """Redact all of ``text``, preserving a trailing newline if present.

    Multi-line patterns (a PEM private-key block) are scrubbed against the
    WHOLE text first, since they can never match within a single line; the
    result is then processed line-by-line for the ``KEY=VALUE``-aware and
    per-line value-pattern redaction.
    """
    trailing_newline = text.endswith("\n")
    prescrubbed = text
    for pat in _MULTILINE_WHOLE:
        prescrubbed = pat.sub(REDACTED, prescrubbed)
    lines = prescrubbed.splitlines()
    out = "\n".join(redact_line(line) for line in lines)
    if trailing_newline and out:
        out += "\n"
    elif trailing_newline and not out:
        out = "\n"
    return out


def main(argv: list[str]) -> int:
    del argv  # no flags today — stdin in, redacted stdout out
    data = sys.stdin.read()
    sys.stdout.write(redact_text(data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
