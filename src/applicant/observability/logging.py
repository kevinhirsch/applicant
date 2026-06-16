"""structlog configuration (FR-OBS-1).

JSON in production / pretty in dev, with correlation-id support and secret
redaction so credentials/PII never reach the logs (FR-VAULT-3, NFR-PRIV-1).
"""

from __future__ import annotations

import logging
import re
from collections import deque
from contextvars import ContextVar
from typing import Any

import structlog

#: Bounded in-memory ring buffer of recent (already-redacted) log events, so the
#: debug surface can tail structured logs without a separate log store (FR-OBS-2,
#: FR-LOG-3). It is the LAST processor's input, so secrets are already redacted.
_LOG_RING: deque[dict] = deque(maxlen=500)


def recent_logs(limit: int = 100) -> list[dict]:
    """Return the most-recent redacted log entries, newest last (FR-LOG-3)."""
    items = list(_LOG_RING)
    return items[-limit:] if limit else items


def _capture_log(_logger: Any, _method: str, event_dict: dict) -> dict:
    """structlog processor: snapshot the (redacted) event into the ring buffer.

    Runs AFTER ``_redact_secrets`` so nothing sensitive is retained (NFR-PRIV-1).
    """
    _LOG_RING.append({k: _to_jsonable(v) for k, v in event_dict.items()})
    return event_dict


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(v) for v in value]
    return str(value)

#: Per-request/per-application correlation id, bound into every log line.
correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)

#: Keys whose values must never appear in logs.
_SECRET_KEYS = frozenset(
    {
        "password",
        "secret",
        "api_key",
        "apikey",
        "token",
        "authorization",
        "credential",
        "llm_api_key",
        "discord_webhook_url",
        "master_key",
        "ssn",
    }
)

_REDACTED = "***REDACTED***"

#: Value-based secret patterns (NFR-PRIV-1): a secret in a NON-secret-named key, or
#: embedded in a free-text message string, is masked too — key-name redaction alone
#: is not enough. Each pattern matches the secret token (a group masked in place) so
#: surrounding text is preserved. Kept cheap: a handful of anchored substrings.
_SECRET_VALUE_PATTERNS: tuple[re.Pattern[str], ...] = (
    # JWT: three base64url segments separated by dots.
    re.compile(r"\beyJ[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\b"),
    # OpenAI-style keys: sk-..., sk-proj-..., and generic provider key prefixes.
    re.compile(r"\b(?:sk|rk|pk|xoxb|ghp|gho|ghs|AKIA|ASIA)[-_][A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    # Bearer tokens in an Authorization-style string.
    re.compile(r"(?i)\b(?:bearer|token|api[_-]?key|authorization)\b[=:\s]+\S{8,}"),
    # password=... / pwd: ... inline in a message.
    re.compile(r"(?i)\b(?:password|passwd|pwd|secret)\b[=:\s]+\S{4,}"),
)
#: A long high-entropy bare token (32+ url-safe chars, mixed case+digits) — a
#: catch-all for opaque credentials embedded with no telltale prefix.
_HIGH_ENTROPY = re.compile(r"\b(?=[A-Za-z0-9_-]*[A-Za-z])(?=[A-Za-z0-9_-]*\d)[A-Za-z0-9_-]{32,}\b")


def _redact_text(text: str) -> str:
    """Mask secret-looking tokens embedded anywhere in a string (cheap, NFR-PRIV-1)."""
    if not text or len(text) < 8:
        return text
    redacted = text
    for pat in _SECRET_VALUE_PATTERNS:
        redacted = pat.sub(_REDACTED, redacted)
    redacted = _HIGH_ENTROPY.sub(_REDACTED, redacted)
    return redacted


def _redact_value(value: Any) -> Any:
    """Recursively redact secret-looking keys AND secret-looking values.

    Key-name redaction (the secret-named key) is supplemented with value-based
    redaction: a secret under a non-obvious key, or embedded in a string, is masked
    too — so a token never leaks via an innocuously-named field (NFR-PRIV-1).
    """
    if isinstance(value, dict):
        return {
            k: (_REDACTED if k.lower() in _SECRET_KEYS else _redact_value(v))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return type(value)(_redact_value(v) for v in value)
    if isinstance(value, str):
        return _redact_text(value)
    return value


def _redact_secrets(_logger: Any, _method: str, event_dict: dict) -> dict:
    """structlog processor: redact secret-looking keys AND values (recursively)."""
    for key in list(event_dict.keys()):
        if key.lower() in _SECRET_KEYS:
            event_dict[key] = _REDACTED
        else:
            event_dict[key] = _redact_value(event_dict[key])
    return event_dict


def _add_correlation_id(_logger: Any, _method: str, event_dict: dict) -> dict:
    """structlog processor: attach the current correlation id if set."""
    cid = correlation_id.get()
    if cid is not None:
        event_dict.setdefault("correlation_id", cid)
    return event_dict


def bind_correlation_id(cid: str) -> Any:
    """Bind a correlation id for the current context (per-run/per-application).

    Returns the contextvars token so callers can ``reset`` it later (FR-OBS-1).
    """
    return correlation_id.set(cid)


#: OTel/DBOS trace-hook seam. Real deployments install a tracer-provider hook here
#: (DBOS emits OTel spans, FR-OBS-1); the default no-op keeps the suite hermetic.
_trace_hook: Any = None


def set_trace_hook(hook: Any) -> None:
    """Install a tracing hook (e.g. an OTel exporter / DBOS tracer). FR-OBS-1."""
    global _trace_hook
    _trace_hook = hook


def get_trace_hook() -> Any:
    """Return the installed trace hook (or ``None`` if tracing is off)."""
    return _trace_hook


def configure_logging(*, log_format: str = "pretty", log_level: str = "INFO") -> None:
    """Configure structlog once at startup.

    Args:
        log_format: ``"json"`` for production, ``"pretty"`` for dev.
        log_level: standard logging level name.
    """
    level = getattr(logging, log_level.upper(), logging.INFO)
    logging.basicConfig(format="%(message)s", level=level)

    renderer: Any = (
        structlog.processors.JSONRenderer()
        if log_format.lower() == "json"
        else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _add_correlation_id,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            _redact_secrets,
            _capture_log,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> Any:
    """Return a bound structlog logger."""
    return structlog.get_logger(name)
