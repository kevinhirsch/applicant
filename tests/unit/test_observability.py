"""Observability: secret redaction + correlation-id propagation (FR-OBS-1).

``structlog.testing.capture_logs`` short-circuits the processor chain, so these
tests exercise the redaction / correlation-id processors directly (they are the
exact callables wired into ``configure_logging``).
"""

from __future__ import annotations

from applicant.observability import logging as obs


def test_secret_keys_redacted_top_level():
    out = obs._redact_secrets(None, "info", {"api_key": "sk-1", "token": "t", "normal": "ok"})
    assert out["api_key"] == "***REDACTED***"
    assert out["token"] == "***REDACTED***"
    assert out["normal"] == "ok"


def test_secret_keys_redacted_nested():
    out = obs._redact_secrets(
        None,
        "info",
        {"config": {"model": "gpt", "api_key": "sk-secret", "nested": {"password": "p"}}},
    )
    cfg = out["config"]
    assert cfg["model"] == "gpt"
    assert cfg["api_key"] == "***REDACTED***"
    assert cfg["nested"]["password"] == "***REDACTED***"


def test_secret_keys_redacted_in_list():
    out = obs._redact_secrets(
        None, "info", {"tiers": [{"model": "m", "api_key": "sk-x"}]}
    )
    assert out["tiers"][0]["api_key"] == "***REDACTED***"
    assert out["tiers"][0]["model"] == "m"


def test_secret_value_in_message_string_is_masked():
    # FR-OBS-1 / NFR-PRIV-1: a secret embedded in a free-text message is masked.
    out = obs._redact_secrets(
        None, "info", {"event": "calling provider with sk-ABCD1234efgh5678ijkl9012"}
    )
    assert "sk-ABCD1234efgh5678ijkl9012" not in out["event"]
    assert obs._REDACTED in out["event"]
    # Surrounding text is preserved.
    assert out["event"].startswith("calling provider with")


def test_secret_value_under_non_obvious_key_is_masked():
    # FR-OBS-1: a secret stored under an innocuous key name is still masked by value.
    jwt = "eyJhbGciOi.eyJzdWIiOiIxMjM0NTY3ODkw.SflKxwRJSMeKKF2QT4fwpMeJf36"
    out = obs._redact_secrets(None, "info", {"detail": jwt, "note": "ok"})
    assert out["detail"] == obs._REDACTED
    assert out["note"] == "ok"


def test_bearer_and_password_inline_are_masked():
    out = obs._redact_secrets(
        None,
        "info",
        {"hdr": "Authorization: Bearer abcdef123456ghijkl", "msg": "password=hunter2x"},
    )
    assert "abcdef123456ghijkl" not in out["hdr"]
    assert "hunter2x" not in out["msg"]


def test_high_entropy_token_under_plain_key_is_masked():
    out = obs._redact_secrets(
        None, "info", {"opaque": "Ab3" + "x9Z2k" * 7}  # 38 mixed chars, no prefix
    )
    assert out["opaque"] == obs._REDACTED


def test_normal_text_is_untouched():
    # Ordinary words / short ids / plain sentences are not over-redacted.
    msg = "Scanning enabled sources for new viable roles to add to today's digest."
    out = obs._redact_secrets(None, "info", {"event": msg, "count": 7, "id": "app-123"})
    assert out["event"] == msg
    assert out["count"] == 7
    assert out["id"] == "app-123"


def test_correlation_id_propagates():
    token = obs.bind_correlation_id("run-abc")
    try:
        out = obs._add_correlation_id(None, "info", {})
        assert out["correlation_id"] == "run-abc"
    finally:
        obs.correlation_id.reset(token)


def test_correlation_id_absent_when_unset():
    obs.correlation_id.set(None)
    out = obs._add_correlation_id(None, "info", {})
    assert "correlation_id" not in out


def test_configure_logging_smoke():
    # Sanity: configuration applies without error in both formats.
    obs.configure_logging(log_format="json", log_level="INFO")
    obs.configure_logging(log_format="pretty", log_level="DEBUG")
    obs.get_logger("test").info("ok")


def test_trace_hook_seam():
    assert obs.get_trace_hook() is None
    sentinel = object()
    obs.set_trace_hook(sentinel)
    try:
        assert obs.get_trace_hook() is sentinel
    finally:
        obs.set_trace_hook(None)
