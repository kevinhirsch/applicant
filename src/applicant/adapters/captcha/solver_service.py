"""SolverServiceAdapter — the SOLVE leg of the captcha solver port (#350).

Interactive captcha families (reCAPTCHA v2 checkbox, hCaptcha, and Turnstile in
challenge mode) are resolved by farming the challenge to a third-party solving service
(CapSolver / 2Captcha / Anti-Captcha) which returns a response *token*. We then inject
that token into the page's hidden response field and fire its JS callback so the form
can proceed.

Structure (so the whole thing is hermetically testable with NO live key):

* ``_TokenSolver`` is the ONLY part that talks to the third party. Production wires
  :class:`HttpTokenSolver` (a thin scaffold around the service HTTP API, the single
  piece that needs a live ``CAPTCHA_API_KEY``). Tests inject a mock solver callable
  that returns a fixed token — so classification, token injection (right field +
  callback), and secret-redaction are all exercised without a network or a key.
* The ``api_key`` is sealed via the credential vault upstream and is NEVER logged: it
  is held only inside the solver, redacted from this adapter's ``repr``, and every log
  line scrubs it.

This adapter NEVER bypasses the pre-fill stop-boundary: it only resolves the captcha
gate; account-create / final-submit remain irreducible human steps enforced elsewhere.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from applicant.ports.driven.captcha import (
    CaptchaContext,
    CaptchaDisposition,
    CaptchaKind,
    CaptchaOutcome,
)

log = logging.getLogger(__name__)

#: Interactive families this service can solve by token injection.
_SOLVABLE = frozenset(
    {CaptchaKind.RECAPTCHA_V2, CaptchaKind.HCAPTCHA, CaptchaKind.TURNSTILE}
)

#: Per-family hidden response field + callback name the token is injected into.
#: reCAPTCHA writes to ``g-recaptcha-response``; hCaptcha to ``h-captcha-response``;
#: Turnstile to ``cf-turnstile-response``. The detector may override via the context.
_FIELD_DEFAULTS: dict[CaptchaKind, str] = {
    CaptchaKind.RECAPTCHA_V2: "g-recaptcha-response",
    CaptchaKind.HCAPTCHA: "h-captcha-response",
    CaptchaKind.TURNSTILE: "cf-turnstile-response",
}


@runtime_checkable
class TokenInjector(Protocol):
    """Writes a solved token into the page and fires the widget callback.

    The real browser adapter provides this (it evaluates JS in the live page); tests
    provide a recording fake so injection is asserted without a browser.
    """

    def inject_captcha_token(
        self, *, field: str, token: str, callback: str = ""
    ) -> bool:
        """Write ``token`` into the hidden ``field`` and fire ``callback`` if set.

        Returns True on success. The token is the solver's response value, never a
        secret — but the field/callback wiring is the load-bearing bit under test.
        """
        ...


#: A solver call: (kind, site_key, page_url) -> response token, or None on failure.
TokenSolver = Callable[[CaptchaKind, str, str], "str | None"]


@dataclass(frozen=True)
class HttpTokenSolver:
    """Scaffold for the real third-party solver HTTP call (the live-key-only part).

    Holds the sealed ``api_key`` (redacted from ``repr``). ``__call__`` is the single
    seam that, in production, POSTs the challenge to the service and polls for the
    token. Until a live HTTP client is wired it returns ``None`` (degrade → hand-off),
    so importing/constructing it is always safe and never leaks the key.
    """

    api_key: str
    service: str = "capsolver"
    egress_proxy: str = ""

    def __repr__(self) -> str:  # never render the key
        return f"HttpTokenSolver(service={self.service!r}, api_key=***)"

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def __call__(
        self, kind: CaptchaKind, site_key: str, page_url: str
    ) -> str | None:
        # The ONLY live-key-dependent path. Intentionally a no-op scaffold here: the
        # actual service HTTP call (create task → poll → token) is wired at deploy
        # time behind a real key. Returning None degrades cleanly to the hand-off.
        if not self.is_configured():
            return None
        log.info(
            "captcha solver: would submit %s challenge for %s to service %s",
            kind.value,
            page_url,
            self.service,
        )
        return None


class SolverServiceAdapter:
    """Resolve interactive captchas via a token solver + page injection.

    Implements :class:`applicant.ports.driven.captcha.CaptchaSolverPort`.
    """

    def __init__(
        self,
        *,
        solver: TokenSolver | None = None,
        injector: TokenInjector | None = None,
        api_key: str = "",
    ) -> None:
        # ``solver`` is the swap point: production passes an HttpTokenSolver, tests a
        # mock callable. When absent, build the HTTP scaffold from the sealed key.
        self._solver: TokenSolver | None = solver or (
            HttpTokenSolver(api_key=api_key) if api_key else None
        )
        self._injector = injector
        # Held only to answer ``is_configured`` and NEVER logged; redacted from repr.
        self._api_key = api_key

    def __repr__(self) -> str:  # never render the key
        return f"SolverServiceAdapter(configured={self.is_configured()}, api_key=***)"

    def is_configured(self) -> bool:
        if self._solver is None:
            return False
        cfg = getattr(self._solver, "is_configured", None)
        if callable(cfg):
            return bool(cfg())
        return True

    def classify(self, context: CaptchaContext) -> CaptchaDisposition:
        if (
            context.kind in _SOLVABLE
            and context.site_key
            and self.is_configured()
        ):
            return CaptchaDisposition.SOLVE
        return CaptchaDisposition.HANDOFF

    def resolve(self, context: CaptchaContext) -> CaptchaOutcome:
        if self.classify(context) is not CaptchaDisposition.SOLVE:
            return CaptchaOutcome(
                disposition=CaptchaDisposition.HANDOFF,
                solved=False,
                detail="solver off / unsupported captcha; deferring to hand-off",
            )
        assert self._solver is not None  # guarded by classify → is_configured
        try:
            token = self._solver(context.kind, context.site_key, context.url)
        except Exception:  # noqa: BLE001 — a failed solve must degrade, never crash
            log.warning(
                "captcha solver call failed for %s; falling back to hand-off",
                context.url,
                exc_info=True,
            )
            token = None
        if not token:
            return CaptchaOutcome(
                disposition=CaptchaDisposition.HANDOFF,
                solved=False,
                detail="solver returned no token; deferring to hand-off",
            )

        field = context.response_field or _FIELD_DEFAULTS.get(
            context.kind, "g-recaptcha-response"
        )
        injected = self._inject(field=field, token=token, callback=context.callback)
        if not injected:
            return CaptchaOutcome(
                disposition=CaptchaDisposition.HANDOFF,
                solved=False,
                detail="token injection failed; deferring to hand-off",
            )
        # NB: the token value itself is the solver's response (not a secret), but we
        # still keep it out of the detail string by habit — only the field is logged.
        log.info("captcha solver: injected token into %s for %s", field, context.url)
        return CaptchaOutcome(
            disposition=CaptchaDisposition.SOLVE,
            solved=True,
            detail=f"solved {context.kind.value}; token injected into {field}",
        )

    def _inject(self, *, field: str, token: str, callback: str) -> bool:
        if self._injector is None:
            return False
        try:
            return bool(
                self._injector.inject_captcha_token(
                    field=field, token=token, callback=callback
                )
            )
        except Exception:  # noqa: BLE001
            log.warning("captcha token injection raised", exc_info=True)
            return False
