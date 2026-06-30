"""BehavioralAvoidanceStrategy — the AVOID leg of the captcha solver port (#350).

Score/behavioral captcha systems (reCAPTCHA v3, Cloudflare Turnstile in managed
mode) gate on whether the visitor *looks* human, not on a solvable challenge. The
heavy lifting is camoufox's job — its coherent fingerprint + the shipped human-cadence
stealth layer (``adapters.browser.stealth``) is exactly the right defence. This adapter
is therefore intentionally minimal: it classifies the score/behavioral families as
``AVOID`` (proceed) and exposes a couple of cadence helpers wired off the SAME stealth
primitives, so there is a real seam without duplicating the avoidance engine.

It NEVER produces a ``solved`` outcome — avoidance means "proceed without a token".
"""

from __future__ import annotations

import random

from applicant.adapters.browser.stealth import HumanInteraction
from applicant.ports.driven.captcha import (
    CaptchaContext,
    CaptchaDisposition,
    CaptchaKind,
    CaptchaOutcome,
)

#: The captcha families this strategy can avoid (score/behavioral, not interactive).
_AVOIDABLE = frozenset({CaptchaKind.RECAPTCHA_V3, CaptchaKind.TURNSTILE})


class BehavioralAvoidanceStrategy:
    """Avoid score-based captchas by leaning on the shipped stealth layer.

    Implements :class:`applicant.ports.driven.captcha.CaptchaSolverPort`.
    """

    def __init__(self, rng: random.Random | None = None) -> None:
        # Reuse the shipped human-cadence primitive (deterministic when a seeded rng
        # is injected) so the cadence hint here is the same engine the planner uses.
        self._human = HumanInteraction(rng)

    def classify(self, context: CaptchaContext) -> CaptchaDisposition:
        if context.kind in _AVOIDABLE:
            return CaptchaDisposition.AVOID
        return CaptchaDisposition.HANDOFF

    def resolve(self, context: CaptchaContext) -> CaptchaOutcome:
        disposition = self.classify(context)
        if disposition is CaptchaDisposition.AVOID:
            # Warm a human-like cadence before proceeding. The real avoidance is the
            # browser fingerprint + Playwright input pacing; this just advances the
            # logical clock so the seam is exercised and observable.
            self._human.think_delay()
            return CaptchaOutcome(
                disposition=CaptchaDisposition.AVOID,
                solved=False,
                detail=f"score-based {context.kind.value}: proceeding via stealth",
            )
        return CaptchaOutcome(
            disposition=CaptchaDisposition.HANDOFF,
            solved=False,
            detail="not a score-based captcha; deferring to hand-off",
        )
