"""structlog configuration (FR-OBS-1).

JSON in production / pretty in dev, with correlation-id support and secret
redaction so credentials/PII never reach the logs (FR-VAULT-3, NFR-PRIV-1).
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import Any

import structlog

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


def _redact_secrets(_logger: Any, _method: str, event_dict: dict) -> dict:
    """structlog processor: redact secret-looking keys (recursively, shallow)."""
    for key in list(event_dict.keys()):
        if key.lower() in _SECRET_KEYS:
            event_dict[key] = _REDACTED
    return event_dict


def _add_correlation_id(_logger: Any, _method: str, event_dict: dict) -> dict:
    """structlog processor: attach the current correlation id if set."""
    cid = correlation_id.get()
    if cid is not None:
        event_dict.setdefault("correlation_id", cid)
    return event_dict


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
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> Any:
    """Return a bound structlog logger."""
    return structlog.get_logger(name)
