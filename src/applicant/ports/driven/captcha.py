"""CaptchaSolverPort — the opt-in, safe-by-default CAPTCHA driven port (issue #350).

A *single* driven port placed in FRONT of the existing captcha human-handoff in the
pre-fill loop (``prefill_service`` captcha ``StopOp`` → ``BLOCKED_DETECTION``). It
defaults to that handoff, so with the shipped config the engine behaves byte-for-byte
as it does today.

Two beasts, opposite tactics (see ``enh_350_captcha_solver_port.feature``):

* **Score / behavioral systems** (reCAPTCHA v3, Cloudflare Turnstile) are *avoided*
  by looking human — the shipped camoufox coherent-fingerprint + human-cadence stealth
  layer does the heavy lifting; :class:`CaptchaChallenge.AVOID` means "proceed, the
  stealth layer already makes a challenge unlikely".
* **Challenge systems** (reCAPTCHA v2 checkbox, hCaptcha) are *solved* by farming the
  challenge to a third-party solver service and injecting the returned response token
  into the page's hidden field + firing the JS callback.

The **human hand-off** is both the default strategy and the ultimate backstop: when
the strategy is ``human``, the solver is unconfigured, or a solve fails, the run pauses
and escalates to the operator exactly as before. NOTHING here ever lets the engine
self-authorize past the account-create / final-submit stop-boundary — those remain
irreducible human steps; this port only removes the *captcha* manual step when the
operator explicitly opts in.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


class CaptchaKind(str, enum.Enum):
    """The captcha family detected on a page.

    The score/behavioral families (``RECAPTCHA_V3``, ``TURNSTILE``) are *avoided*;
    the interactive families (``RECAPTCHA_V2``, ``HCAPTCHA``) are *solved* by token
    injection. ``UNKNOWN`` falls back to the human hand-off.
    """

    RECAPTCHA_V2 = "recaptcha_v2"
    RECAPTCHA_V3 = "recaptcha_v3"
    HCAPTCHA = "hcaptcha"
    TURNSTILE = "turnstile"
    UNKNOWN = "unknown"


class CaptchaDisposition(str, enum.Enum):
    """How the solver port decided to handle a detected captcha."""

    #: Score/behavioral — proceed; the stealth layer makes a challenge unlikely.
    AVOID = "avoid"
    #: Interactive challenge — farm to the solver service and inject the token.
    SOLVE = "solve"
    #: Hand off to the human operator (default + backstop).
    HANDOFF = "handoff"


@dataclass(frozen=True)
class CaptchaContext:
    """Everything the solver port needs to classify and (maybe) solve a captcha.

    Built at the pre-fill stop-boundary from the current page. ``site_key`` and the
    DOM ``response_field`` / ``callback`` are only known for interactive challenges;
    they are empty for score-based systems (which carry no operator-resolvable token).
    """

    url: str
    kind: CaptchaKind = CaptchaKind.UNKNOWN
    #: The site/widget key the solver service needs (reCAPTCHA/hCaptcha/Turnstile).
    site_key: str = ""
    #: The hidden ``<textarea>``/``<input>`` selector the response token is written to.
    #: Defaults to the reCAPTCHA convention; overridden per-family by the detector.
    response_field: str = "g-recaptcha-response"
    #: The JS callback to invoke after injecting the token (empty ⇒ none).
    callback: str = ""
    #: The deep link to the live takeover session (for the human-handoff path).
    session_url: str = ""
    #: Opaque extra detector signal (e.g. a score, ``data-*`` attributes).
    extra: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class CaptchaOutcome:
    """The result of routing a captcha through the solver port.

    ``disposition`` says what happened; ``solved`` is True ONLY when an interactive
    challenge was solved AND its token injected, so the caller may continue the form.
    For ``AVOID`` the caller proceeds without a token; for ``HANDOFF`` the caller runs
    the existing stop-boundary hand-off (``solved`` is False).
    """

    disposition: CaptchaDisposition
    solved: bool = False
    #: Human-readable, secret-free detail for logs / the pending action.
    detail: str = ""


@runtime_checkable
class CaptchaSolverPort(Protocol):
    """Driven port: classify a detected captcha and resolve it per the strategy.

    A single ``resolve`` entrypoint keeps the pre-fill wiring point a one-liner that
    defaults to the human hand-off. The concrete strategy adapters
    (:class:`BehavioralAvoidanceStrategy`, :class:`SolverServiceAdapter`,
    :class:`HumanHandoffAdapter`) implement this; the composite
    :class:`CaptchaSolver` selects between them from config.
    """

    def classify(self, context: CaptchaContext) -> CaptchaDisposition:
        """Classify a detected captcha into avoid / solve / handoff.

        Pure decision, no side effects — score/behavioral families ⇒ ``AVOID``,
        interactive families with a site key ⇒ ``SOLVE`` (when a solver is
        configured), everything else ⇒ ``HANDOFF``.
        """
        ...

    def resolve(self, context: CaptchaContext) -> CaptchaOutcome:
        """Resolve a detected captcha, returning the :class:`CaptchaOutcome`.

        Never raises for an ordinary failure — a failed solve degrades to a
        ``HANDOFF`` outcome so the caller falls back to the human stop-boundary.
        """
        ...
