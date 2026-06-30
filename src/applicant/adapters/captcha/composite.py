"""CaptchaSolver — the composite captcha solver port the pre-fill loop calls (#350).

Selects between the three strategy adapters from the configured ``CAPTCHA_STRATEGY``:

* ``human`` (DEFAULT) — only the hand-off is active; behaves byte-for-byte as today.
* ``avoid``  — score/behavioral families proceed via stealth; everything else hands off.
* ``service`` — interactive challenges are solved by token injection; score/behavioral
  families still proceed via stealth; failures and unsupported families hand off.

``resolve`` NEVER raises for an ordinary failure: an unconfigured/failed solve degrades
to a ``HANDOFF`` outcome so the pre-fill loop falls back to the existing stop-boundary.
The composite owns ZERO bypass of the account-create / final-submit boundary — it only
decides whether the *captcha* gate is avoided, solved, or handed off.
"""

from __future__ import annotations

from applicant.adapters.captcha.behavioral_avoidance import BehavioralAvoidanceStrategy
from applicant.adapters.captcha.human_handoff import HumanHandoffAdapter
from applicant.adapters.captcha.solver_service import SolverServiceAdapter
from applicant.ports.driven.captcha import (
    CaptchaContext,
    CaptchaDisposition,
    CaptchaOutcome,
)

STRATEGY_HUMAN = "human"
STRATEGY_AVOID = "avoid"
STRATEGY_SERVICE = "service"
STRATEGIES = (STRATEGY_HUMAN, STRATEGY_AVOID, STRATEGY_SERVICE)


class CaptchaSolver:
    """Config-driven composite over the three captcha strategy adapters.

    Implements :class:`applicant.ports.driven.captcha.CaptchaSolverPort`.
    """

    def __init__(
        self,
        *,
        strategy: str = STRATEGY_HUMAN,
        avoidance: BehavioralAvoidanceStrategy | None = None,
        service: SolverServiceAdapter | None = None,
        handoff: HumanHandoffAdapter | None = None,
    ) -> None:
        self._strategy = strategy if strategy in STRATEGIES else STRATEGY_HUMAN
        self._avoidance = avoidance or BehavioralAvoidanceStrategy()
        self._service = service
        self._handoff = handoff or HumanHandoffAdapter()

    @property
    def strategy(self) -> str:
        return self._strategy

    def classify(self, context: CaptchaContext) -> CaptchaDisposition:
        # ``human`` short-circuits: every captcha hands off, byte-for-byte as today.
        if self._strategy == STRATEGY_HUMAN:
            return CaptchaDisposition.HANDOFF
        # Score/behavioral families always prefer avoidance (both avoid + service modes
        # lean on stealth for these — there is no solvable token).
        avoid = self._avoidance.classify(context)
        if avoid is CaptchaDisposition.AVOID:
            return CaptchaDisposition.AVOID
        # Interactive challenge: only the service mode can solve it.
        if self._strategy == STRATEGY_SERVICE and self._service is not None:
            return self._service.classify(context)
        return CaptchaDisposition.HANDOFF

    def resolve(self, context: CaptchaContext) -> CaptchaOutcome:
        disposition = self.classify(context)
        if disposition is CaptchaDisposition.AVOID:
            return self._avoidance.resolve(context)
        if disposition is CaptchaDisposition.SOLVE and self._service is not None:
            outcome = self._service.resolve(context)
            # A failed solve degrades to hand-off (outcome already says HANDOFF).
            return outcome
        return self._handoff.resolve(context)
