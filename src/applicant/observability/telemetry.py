"""Opt-in error telemetry (P5-3): crash reporting that respects the privacy story.

The DoD is one sentence — "crash reporting that respects the privacy story;
opt-in; actionable" — but this module is the one place that sentence is made
true, so every guarantee lives here, not in the caller:

* **Opt-in, default OFF.** Nothing is ever sent unless an operator explicitly
  turns it on in Settings (persisted via ``SetupService.configure_telemetry``,
  mirroring the existing notification-channels opt-in). ``TelemetryReporter``
  never accepts an ``enabled``/``effective`` argument from a caller — the ONLY
  way it decides whether to send is by calling the injected ``status_fn``,
  which reads the server's own persisted config + the live local-only flag
  fresh on every call (H2: never cached to the point of going stale, never
  trusted from a caller-supplied flag — same discipline as the fabrication
  guard's own ground truth in ``core/rules/sensitive_fields.py``).
* **Hard off in local-only private mode.** ``status_fn`` (wired from
  ``SetupService.telemetry_status``) folds in ``local_only`` and reports
  ``effective=False`` whenever it is on, REGARDLESS of the stored "enabled"
  preference — mirrors the same "config stored untouched, enforcement
  computed at the one gate every consumer reads" shape ``docs/private-mode.md``
  already documents for the LLM tier ladder.
* **Redaction chokepoint.** ``build_crash_event`` is the ONLY place a payload
  is assembled, and it is the ONLY place allowed to touch the exception's
  message/traceback. It reuses ``observability.logging.redact_text`` — the
  SAME secret-scrubbing patterns (API keys, bearer tokens, JWTs, password=
  strings, URL userinfo, high-entropy tokens) already trusted to keep secrets
  out of the logs — rather than a second, divergent pattern list. Stack frames
  are reduced to ``basename:lineno in function`` so a path like
  ``/home/alice/apps/applicant/...`` never reaches the payload (no usernames,
  no local filesystem layout). No résumé/job/profile content is ever in scope:
  the payload has exactly eight keys (below) and nothing else is walked in.
* **Actionable, not verbose.** The payload is the minimum a maintainer needs
  to triage: exception class, a redacted one-line message, which component
  raised it, the app version, a coarse platform string, and a short redacted
  stack — never request/response bodies, never user input.
* **No hardcoded vendor.** There is no Applicant-operated collection
  endpoint. Sending is a no-op unless the operator supplies their OWN sink URL
  (self-hosted, or any HTTP collector they choose) — see ``docs/private-mode.md``
  and the privacy policy for the honest statement of this choice.
"""

from __future__ import annotations

import sys
import time
import traceback
from typing import Any, Protocol

from applicant.observability.logging import get_logger, redact_text

log = get_logger(__name__)

#: Bound on how many trailing stack frames ride along — enough to triage,
#: never the whole call graph.
_MAX_FRAMES = 8
#: Bound on the redacted message length so a pathological exception message
#: (e.g. one that embeds a large blob) can't balloon the payload.
_MAX_MESSAGE_CHARS = 500


def _coarse_platform() -> str:
    """A coarse, non-identifying platform string: OS family + Python version.

    Deliberately NOT ``platform.node()``/hostname/machine-id — none of which
    are needed to triage a crash signature and all of which are more specific
    than "actionable" requires (NFR-PRIV-1: minimum necessary, not maximum
    available).
    """
    return f"{sys.platform}-py{sys.version_info.major}.{sys.version_info.minor}"


def _redacted_stack(exc: BaseException) -> list[str]:
    """The trailing frames of ``exc``'s traceback, reduced to a filename (not a
    full path — no ``/home/<user>/...``), line number, and function name, each
    redacted the same way a log line's free text is. Bounded to ``_MAX_FRAMES``
    so a deep recursion doesn't inflate the payload."""
    frames = traceback.extract_tb(exc.__traceback__)
    tail = frames[-_MAX_FRAMES:] if len(frames) > _MAX_FRAMES else frames
    out = []
    for frame in tail:
        filename = frame.filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        out.append(redact_text(f"{filename}:{frame.lineno} in {frame.name}"))
    return out


def _route_template(request: Any) -> str:
    """The MATCHED ROUTE'S TEMPLATE (e.g. ``/api/campaigns/{campaign_id}``), never
    the resolved URL — the template has no real ids/query params in it, so it
    can't leak a campaign/posting id. Empty string when unavailable (never
    falls back to the raw path)."""
    try:
        route = request.scope.get("route") if request is not None else None
        return str(getattr(route, "path", "") or "")
    except Exception:  # pragma: no cover - defensive, request shape varies
        return ""


def build_crash_event(
    exc: BaseException,
    *,
    component: str,
    app_version: str,
    route: str = "",
) -> dict:
    """Build the sanitized crash payload — the ONE place a payload is assembled.

    Exactly eight keys: ``exception_type``, ``message`` (redacted, truncated),
    ``component``, ``route`` (a route TEMPLATE, never a resolved path/id),
    ``app_version``, ``platform`` (coarse), ``stack`` (redacted, bounded), and
    ``occurred_at``. No résumé text, no job data, no headers, no request body —
    those are never passed in, so they can never leak here.
    """
    message = redact_text(str(exc))[:_MAX_MESSAGE_CHARS]
    return {
        "exception_type": type(exc).__name__,
        "message": message,
        "component": component,
        "route": redact_text(route)[:200] if route else "",
        "app_version": app_version,
        "platform": _coarse_platform(),
        "stack": _redacted_stack(exc),
        "occurred_at": time.time(),
    }


class TelemetryStatusFn(Protocol):
    def __call__(self) -> dict: ...  # returns {"effective": bool, "endpoint": str, ...}


class TelemetrySender(Protocol):
    def __call__(self, endpoint: str, payload: dict, *, timeout: float) -> None: ...


def _default_sender(endpoint: str, payload: dict, *, timeout: float) -> None:
    """Best-effort POST to the operator-configured sink. Import httpx lazily so
    a hermetic/no-network test importing this module never needs the dependency
    reachable, and so a send failure can never raise past this function."""
    import httpx

    httpx.post(endpoint, json=payload, timeout=timeout)


class TelemetryReporter:
    """The single call site every crash-reporting caller (the global exception
    handler today; future call sites tomorrow) goes through. Deliberately has
    NO ``enabled``/``force``/``effective`` parameter on ``capture`` — the
    caller cannot opt a report back in; only the server-computed ``status_fn``
    result can (SECURITY: a caller-supplied flag must never bypass a
    privacy/safety gate — the same discipline as the fabrication guard's own
    ground truth).
    """

    def __init__(
        self,
        *,
        status_fn: TelemetryStatusFn,
        app_version: str,
        sender: TelemetrySender | None = None,
        timeout: float = 2.0,
    ) -> None:
        self._status_fn = status_fn
        self._app_version = app_version
        self._sender = sender or _default_sender
        self._timeout = timeout

    def capture(self, exc: BaseException, *, component: str, request: Any = None) -> bool:
        """Report ``exc`` if (and only if) the server-side gate says to.

        Returns whether a send was attempted (for tests/observability) — never
        raises, so a telemetry hiccup can never break the caller's own error
        handling.
        """
        try:
            current = self._status_fn() or {}
        except Exception:  # pragma: no cover - a status hiccup must not raise
            log.debug("telemetry_status_check_failed", exc_info=True)
            return False
        if not current.get("effective"):
            return False
        endpoint = str(current.get("endpoint") or "")
        if not endpoint:
            return False
        route = _route_template(request)
        payload = build_crash_event(
            exc, component=component, app_version=self._app_version, route=route
        )
        try:
            self._sender(endpoint, payload, timeout=self._timeout)
        except Exception:  # pragma: no cover - best-effort, never propagates
            log.debug("telemetry_send_failed", exc_info=True)
        return True
