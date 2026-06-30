"""Build a :class:`CaptchaContext` from the current page state (issue #350).

The pre-fill loop reaches the captcha stop-boundary with a ``PageState`` whose ``body``
carries the rendered markup. This module sniffs the captcha family + site key from that
markup so the solver port can classify it. It is deliberately conservative: when it
can't recognise a family it returns ``UNKNOWN`` (which classifies as a hand-off), so an
unrecognised captcha always degrades to the safe path.
"""

from __future__ import annotations

import re

from applicant.ports.driven.captcha import CaptchaContext, CaptchaKind

# Per-family markers + the attribute the site key lives in. Order matters: hCaptcha and
# Turnstile carry their own widget classes; reCAPTCHA v2 vs v3 is told apart by the
# explicit ``data-size="invisible"`` / ``grecaptcha.execute`` v3 markers.
_HCAPTCHA = re.compile(r"\bh-captcha\b|hcaptcha\.com", re.IGNORECASE)
_TURNSTILE = re.compile(r"\bcf-turnstile\b|challenges\.cloudflare\.com/turnstile", re.IGNORECASE)
_RECAPTCHA = re.compile(r"\bg-recaptcha\b|recaptcha/api", re.IGNORECASE)
_RECAPTCHA_V3 = re.compile(r"recaptcha/api\.js\?render=|grecaptcha\.execute", re.IGNORECASE)
_SITEKEY = re.compile(
    r"""data-sitekey\s*=\s*["']([^"']+)["']|[?&]render=([A-Za-z0-9_-]+)""",
    re.IGNORECASE,
)


def _detect_kind(body: str) -> CaptchaKind:
    if _HCAPTCHA.search(body):
        return CaptchaKind.HCAPTCHA
    if _TURNSTILE.search(body):
        return CaptchaKind.TURNSTILE
    if _RECAPTCHA.search(body):
        if _RECAPTCHA_V3.search(body):
            return CaptchaKind.RECAPTCHA_V3
        return CaptchaKind.RECAPTCHA_V2
    return CaptchaKind.UNKNOWN


def _detect_site_key(body: str) -> str:
    m = _SITEKEY.search(body)
    if not m:
        return ""
    return m.group(1) or m.group(2) or ""


def build_captcha_context(state, *, session_url: str = "") -> CaptchaContext:
    """Construct a :class:`CaptchaContext` from a ``PageState``-like object.

    ``state`` need only expose ``url`` and ``body``; both are tolerated as missing.
    """
    body = getattr(state, "body", None) or ""
    url = getattr(state, "url", "") or ""
    kind = _detect_kind(body)
    return CaptchaContext(
        url=url,
        kind=kind,
        site_key=_detect_site_key(body),
        session_url=session_url,
    )
