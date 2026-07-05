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
        # dark-engine audit #67: process-lived, REAL attempt/outcome counters —
        # incremented only inside ``resolve()`` below, never fabricated. A fresh
        # process (or the default ``human`` strategy, which the container never
        # even builds a solver for) honestly reports zero for all of them.
        self._attempts = 0
        self._solved = 0
        self._avoided = 0
        self._handed_off = 0

    @property
    def strategy(self) -> str:
        return self._strategy

    def stats(self) -> dict:
        """Read-only telemetry snapshot for the Debug surface (dark-engine audit #67).

        The effective strategy + whether a third-party solver service is wired,
        plus the REAL counts this process has recorded resolving captchas so
        far — never a fabricated/estimated number.
        """
        return {
            "strategy": self._strategy,
            "service_configured": self._service is not None,
            "attempts": self._attempts,
            "solved": self._solved,
            "avoided": self._avoided,
            "handed_off": self._handed_off,
        }

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
            outcome = self._avoidance.resolve(context)
        elif disposition is CaptchaDisposition.SOLVE and self._service is not None:
            # A failed solve degrades to hand-off (outcome already says HANDOFF).
            outcome = self._service.resolve(context)
        else:
            outcome = self._handoff.resolve(context)
        self._record(outcome)
        return outcome

    def _record(self, outcome: CaptchaOutcome) -> None:
        """dark-engine audit #67: tally the REAL outcome — read-only bookkeeping,
        no effect on ``outcome`` or the caller's control flow."""
        self._attempts += 1
        if outcome.solved:
            self._solved += 1
        elif outcome.disposition is CaptchaDisposition.AVOID:
            self._avoided += 1
        else:
            self._handed_off += 1
