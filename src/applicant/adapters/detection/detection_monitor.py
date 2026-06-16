"""Detection-monitor adapter (FR-PREFILL-6, FR-STEALTH).

# STAGE B — owned by Phase 2; fleshed out as a thin scaffold.

Classifies CAPTCHA/Turnstile, Cloudflare/DataDome interstitials, 403/429, and
anomalous redirects into a :class:`DetectionEvent` that drives **cautious mode**
(checkpoint, pause, notify with the live-session handoff). It NEVER bypasses or
solves a challenge — it only *signals* (FR-PREFILL-6).
"""

from __future__ import annotations

from applicant.core.entities.detection_event import DetectionEvent
from applicant.core.ids import ApplicationId, DetectionEventId, new_id

#: Substrings (lowercased) in page text/markup that indicate a challenge.
_CHALLENGE_MARKERS: dict[str, str] = {
    "captcha": "captcha",
    "recaptcha": "captcha",
    "hcaptcha": "captcha",
    "turnstile": "turnstile",
    "cf-challenge": "cloudflare",
    "cloudflare": "cloudflare",
    "checking your browser": "cloudflare",
    "datadome": "datadome",
    "are you a robot": "captcha",
    "verify you are human": "captcha",
}

#: HTTP status codes that indicate blocking / rate-limiting (FR-PREFILL-6).
_BLOCKING_STATUSES: frozenset[int] = frozenset({403, 429})

#: Account-creation friction markers (repeated failures, lockouts, "too many
#: attempts") — a cautious-mode trigger per the work package (FR-PREFILL-6).
_FRICTION_MARKERS: tuple[str, ...] = (
    "too many attempts",
    "temporarily locked",
    "account locked",
    "unusual activity",
    "please try again later",
    "suspicious activity",
)


def classify_signals(page_signals: dict) -> str | None:
    """Return a normalized signal type if ``page_signals`` indicate detection.

    ``page_signals`` is a loose dict the browser adapter assembles, e.g.::

        {"status": 429, "body": "...", "signals": ("turnstile",),
         "url": "...", "expected_host": "..."}

    Recognized keys: ``status`` (int), ``body``/``markup`` (str),
    ``signals`` (iterable of strings), and ``url`` + ``expected_host`` for
    anomalous-redirect detection. Returns ``None`` when nothing is detected.
    """
    # 1. HTTP status block / rate-limit.
    status = page_signals.get("status")
    if isinstance(status, int) and status in _BLOCKING_STATUSES:
        return "rate_limited" if status == 429 else "blocked_403"

    # 2. Explicit signals already extracted by the browser adapter.
    explicit = [str(s).lower() for s in page_signals.get("signals", ())]
    haystack = " ".join(explicit)
    body = (page_signals.get("body") or page_signals.get("markup") or "")
    haystack = f"{haystack} {body}".lower()
    for marker, signal_type in _CHALLENGE_MARKERS.items():
        if marker in haystack:
            return signal_type

    # 3. Account-creation friction (lockouts / repeated failures) (FR-PREFILL-6).
    for marker in _FRICTION_MARKERS:
        if marker in haystack:
            return "account_friction"

    # 4. Anomalous redirect: landed on a host we did not expect.
    url = page_signals.get("url")
    expected = page_signals.get("expected_host")
    if url and expected and expected.lower() not in str(url).lower():
        return "anomalous_redirect"

    return None


class DetectionMonitor:
    """DetectionMonitorPort adapter — classifies signals, never solves them."""

    def evaluate(self, application_id: ApplicationId, page_signals: dict) -> DetectionEvent | None:
        """Return a ``DetectionEvent`` if ``page_signals`` indicate detection."""
        signal_type = classify_signals(page_signals)
        if signal_type is None:
            return None
        return DetectionEvent(
            id=DetectionEventId(new_id()),
            application_id=application_id,
            signal_type=signal_type,
            detail={k: v for k, v in page_signals.items() if k != "body"},
        )
