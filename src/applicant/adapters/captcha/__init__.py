"""CAPTCHA solver adapters (issue #350).

Three driven adapters behind :class:`applicant.ports.driven.captcha.CaptchaSolverPort`
plus a composite that selects between them from config:

* :class:`behavioral_avoidance.BehavioralAvoidanceStrategy` — lean on the shipped
  stealth layer so score/behavioral systems (reCAPTCHA v3, Turnstile) never challenge.
* :class:`solver_service.SolverServiceAdapter` — token-injection scaffold for the
  interactive families (reCAPTCHA v2, hCaptcha, Turnstile-as-challenge). The only part
  that needs a live key is the third-party HTTP call; everything around it is
  hermetically testable with a mock solver.
* :class:`human_handoff.HumanHandoffAdapter` — wraps the EXISTING stop-boundary
  hand-off; the default strategy and the ultimate backstop.

:class:`composite.CaptchaSolver` is the front-of-handoff entrypoint the pre-fill loop
calls; with the shipped defaults it routes straight to the human hand-off.
"""

from __future__ import annotations

from applicant.adapters.captcha.behavioral_avoidance import BehavioralAvoidanceStrategy
from applicant.adapters.captcha.composite import CaptchaSolver
from applicant.adapters.captcha.human_handoff import HumanHandoffAdapter
from applicant.adapters.captcha.solver_service import SolverServiceAdapter

__all__ = [
    "BehavioralAvoidanceStrategy",
    "CaptchaSolver",
    "HumanHandoffAdapter",
    "SolverServiceAdapter",
]
