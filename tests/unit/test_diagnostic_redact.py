"""Hermetic coverage for scripts/lib/diagnostic_redact.py (P5-1, "Support
machinery" — the redacted diagnostic-bundle command's redaction core).

Proves the core DoD claim: a known secret fed through the redaction function
is absent from the output, for every shape Applicant's own deploy config and
logs can embed a secret in (a standalone ``KEY=VALUE`` .env line, a secret
embedded mid-sentence in a free-text log line, a DSN with userinfo creds, a
webhook URL with an embedded token, a JWT, a PEM block) — never trusting a
caller flag to skip it (there is none).

Fixture "secrets" are built via string concatenation, mirroring
tests/unit/test_ci_secret_scan.py's own convention, so this file's source
never contains a contiguous secret-shaped literal that would itself trip the
repo's CI secret scanner (scripts/ci/secret_scan.py).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "lib" / "diagnostic_redact.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("diagnostic_redact", _MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


d = _load_module()

# Fixture secrets, concatenation-built (see module docstring).
_FAKE_PASSWORD = "hunter2" + "SuperSecretPW9"
_FAKE_TOKEN = "deadbeef" + "cafebabe" + "01234567"
_FAKE_SK_KEY = "sk-ant-api03-" + "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
_FAKE_GH_TOKEN = "ghp_" + "a" * 40
_FAKE_JWT = (
    "eyJhbGciOiJIUzI1NiJ9"
    + "."
    + "eyJzdWIiOiIxMjM0NTY3ODkwIn0"
    + "."
    + "dGhpc2lzYXNlY3JldHNpZ25hdHVyZQ"
)
_FAKE_WEBHOOK_TOKEN = "AbCdEfGhIjKlMnOpQrStUvWxYz" + "1234567890"


def test_module_is_importable():
    # Guards against the CI step regressing to an uncaught SyntaxError.
    _load_module()


def test_redacts_a_standalone_secret_key_env_line():
    text = f"POSTGRES_PASSWORD={_FAKE_PASSWORD}\n"
    out = d.redact_text(text)
    assert _FAKE_PASSWORD not in out
    assert "POSTGRES_PASSWORD=" in out
    assert d.REDACTED in out


def test_redacts_internal_token_and_api_key_lines():
    text = f"APPLICANT_INTERNAL_TOKEN={_FAKE_TOKEN}\nLLM_API_KEY={_FAKE_SK_KEY}\n"
    out = d.redact_text(text)
    assert _FAKE_TOKEN not in out
    assert _FAKE_SK_KEY not in out


def test_redacts_database_url_dsn_with_embedded_credentials():
    text = f"DATABASE_URL=postgresql+psycopg://applicant:{_FAKE_PASSWORD}@postgres:5432/applicant\n"
    out = d.redact_text(text)
    assert _FAKE_PASSWORD not in out
    assert "DATABASE_URL=" in out


def test_keeps_non_secret_keys_untouched():
    text = "APP_PORT=8123\nBROWSER_ENGINE=camoufox\n"
    out = d.redact_text(text)
    assert out == text


def test_redacts_a_secret_embedded_mid_sentence_in_a_free_text_log_line():
    # This is the shape a real `docker compose logs` line takes — NOT a bare
    # KEY=VALUE line, so this exercises the value-pattern fallback rather than
    # the key-name denylist.
    line = f"connecting to postgres with POSTGRES_PASSWORD={_FAKE_PASSWORD} token={_FAKE_GH_TOKEN}\n"
    out = d.redact_text(line)
    assert _FAKE_PASSWORD not in out
    assert _FAKE_GH_TOKEN not in out


def test_redacts_a_jwt_anywhere_in_text():
    line = f"Authorization header seen: Bearer {_FAKE_JWT}\n"
    out = d.redact_text(line)
    assert _FAKE_JWT not in out


def test_redacts_url_userinfo_credentials_but_keeps_the_scheme_and_host():
    line = f"smtps://mailuser:{_FAKE_PASSWORD}@smtp.example.com:465\n"
    out = d.redact_text(line)
    assert _FAKE_PASSWORD not in out
    assert "smtps://" in out
    assert "smtp.example.com" in out


def test_redacts_a_discord_webhook_token_but_keeps_the_prefix():
    line = f"DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/123456789012345678/{_FAKE_WEBHOOK_TOKEN}\n"
    out = d.redact_text(line)
    assert _FAKE_WEBHOOK_TOKEN not in out
    assert "https://discord.com/api/webhooks/123456789012345678/" in out


def test_redacts_a_pem_private_key_block():
    block = "-----BEGIN RSA PRIVATE " + "KEY-----\nMIIB" + _FAKE_TOKEN + "\n-----END RSA PRIVATE " + "KEY-----\n"
    out = d.redact_text(block)
    assert _FAKE_TOKEN not in out
    assert "BEGIN" not in out
    assert d.REDACTED in out


def test_comments_and_blank_lines_pass_through():
    text = "# a comment\n\nAPP_PORT=8123\n"
    out = d.redact_text(text)
    assert out == text


def test_preserves_lack_of_trailing_newline():
    out = d.redact_text("APP_PORT=8123")
    assert not out.endswith("\n")
