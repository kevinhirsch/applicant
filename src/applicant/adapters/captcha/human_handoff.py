"""HumanHandoffAdapter — the default + backstop leg of the captcha solver port (#350).

This wraps the EXISTING stop-boundary hand-off: when a captcha is encountered, the run
pauses and escalates to the operator (a ``blocked_detection`` PendingAction +
notification + ``BLOCKED_DETECTION`` state) exactly as the engine does today. This
adapter does NOT itself create the PendingAction or flip the state — that stays in the
pre-fill loop's captcha stop-boundary so the safety backstop is owned by the core
service. The adapter's job is to *classify every captcha as HANDOFF* and return the
hand-off outcome, so wiring the solver port in front of the existing handoff defaults
to byte-for-byte today's behavior.

With the shipped config (``CAPTCHA_STRATEGY=human``) this is the only strategy active.
"""

from __future__ import annotations

from applicant.ports.driven.captcha import (
    CaptchaContext,
    CaptchaDisposition,
    CaptchaOutcome,
)


class HumanHandoffAdapter:
    """Always hand a captcha off to the human operator (default + backstop).

    Implements :class:`applicant.ports.driven.captcha.CaptchaSolverPort`.
    """

    def classify(self, context: CaptchaContext) -> CaptchaDisposition:
        return CaptchaDisposition.HANDOFF

    def resolve(self, context: CaptchaContext) -> CaptchaOutcome:
        # Return the hand-off outcome; the pre-fill loop runs the EXISTING
        # stop-boundary (PendingAction + notify + BLOCKED_DETECTION). Never solved.
        return CaptchaOutcome(
            disposition=CaptchaDisposition.HANDOFF,
            solved=False,
            detail="captcha handed off to operator (stop-boundary backstop)",
        )
