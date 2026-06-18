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

#: Widget-style challenges (reCAPTCHA/hCaptcha/Turnstile/DataDome). These are
#: matched ONLY against the explicit ``signals`` tuple the browser adapter assembles
#: — NEVER against the raw page body. Modern login/account pages (Workday, etc.)
#: routinely EMBED an invisible reCAPTCHA Enterprise script, so the token sits in the
#: markup with no active challenge; matching it in raw HTML made the engine hand off
#: on essentially every such page, defeating automate-by-default (FR-PREFILL-6). The
#: adapter only emits these when a challenge element is actually VISIBLE.
_WIDGET_SIGNALS: dict[str, str] = {
    "captcha": "captcha",
    "recaptcha": "captcha",
    "hcaptcha": "captcha",
    "turnstile": "turnstile",
    "datadome": "datadome",
}

#: Interstitial / challenge TEXT that is only present when a block page is actually
#: shown to the user (Cloudflare/CAPTCHA/PerimeterX). Safe to match in the page body
#: because these human-visible phrases do not appear merely from an embedded script.
_INTERSTITIAL_MARKERS: dict[str, str] = {
    "checking your browser": "cloudflare",
    "attention required": "cloudflare",
    "needs to review the security of your connection": "cloudflare",
    "are you a robot": "captcha",
    "verify you are human": "captcha",
    "complete the captcha": "captcha",
    "complete the security check": "captcha",
    "press & hold": "captcha",
    "press and hold": "captcha",
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

    Widget challenges (reCAPTCHA/hCaptcha/Turnstile/DataDome) are recognized ONLY
    from the explicit ``signals`` tuple (which the adapter emits when a challenge is
    actually visible), never from the raw ``body`` — an embedded but invisible
    widget script is not a blocker. Genuine full-page interstitial *phrases* are
    still matched in the body.
    """
    # 1. HTTP status block / rate-limit.
    status = page_signals.get("status")
    if isinstance(status, int) and status in _BLOCKING_STATUSES:
        return "rate_limited" if status == 429 else "blocked_403"

    # 2. Widget challenges — ONLY from the adapter's explicit, visibility-vetted
    #    signal tuple (not raw HTML).
    explicit = " ".join(str(s).lower() for s in page_signals.get("signals", ()))
    for marker, signal_type in _WIDGET_SIGNALS.items():
        if marker in explicit:
            return signal_type

    # 3. Interstitial / friction TEXT — these phrases are only present on an actual
    #    block page, so matching them in the body (or explicit signals) is safe.
    body = (page_signals.get("body") or page_signals.get("markup") or "")
    haystack = f"{explicit} {body}".lower()
    for marker, signal_type in _INTERSTITIAL_MARKERS.items():
        if marker in haystack:
            return signal_type
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
