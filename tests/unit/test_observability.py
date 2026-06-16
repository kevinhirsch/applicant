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
