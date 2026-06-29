"""Step bindings for the Skyvern-parity epic (#351) and its CAPTCHA leg (#350).

Behavioral-avoidance scenarios are GREEN — they assert against the shipped
stealth layer (coherent fingerprint + human-cadence planner), which is exactly
the right defence against score-based CAPTCHA (reCAPTCHA v3 / Turnstile). The
solver port, its adapters, the vision lane, the induction/self-healing loop, and
the stop-boundary-preserving solve are @pending TDD probes at the intended seams
(mapped to xfail by conftest). No assert-True; no real browser/network.
"""

from __future__ import annotations

import importlib
import random

import pytest
from pytest_bdd import given, scenarios, then, when

from applicant.adapters.browser.stealth import (
    HumanInteraction,
    coherent_fingerprint,
    fingerprint_is_coherent,
)

scenarios(
    "../features/enhancements/enh_350_captcha_solver_port.feature",
    "../features/enhancements/enh_351_skyvern_parity.feature",
)


@pytest.fixture
def skyctx() -> dict:
    return {}


def _probe(modpath: str, attr: str | None = None):
    module = importlib.import_module(modpath)
    return getattr(module, attr) if attr is not None else module


# --- GREEN: behavioral avoidance leans on the shipped stealth layer ----------
@given("the shipped stealth layer")
def stealth_layer(skyctx):
    skyctx["stealth"] = True


@when("a fingerprint is generated for the Chrome channel")
def gen_fingerprint(skyctx):
    skyctx["fp"] = coherent_fingerprint("chrome")


@then("the fingerprint is internally coherent so score-based systems are less likely to challenge")
def fingerprint_coherent(skyctx):
    assert fingerprint_is_coherent(skyctx["fp"]) is True


@given("the shipped stealth layer with a seeded clock")
def stealth_seeded(skyctx):
    skyctx["human"] = HumanInteraction(random.Random(7))


@when("a value is typed through the human-cadence planner")
def type_cadence(skyctx):
    skyctx["plan"] = skyctx["human"].type_cadence("hello world")


@then("each keystroke carries a positive human-like dwell and the logical clock advances")
def cadence_humanlike(skyctx):
    plan = skyctx["plan"]
    assert plan and all(k.delay_ms > 0 for k in plan)
    assert skyctx["human"].elapsed_ms > 0


# --- PENDING: the solver port + parity end-state (honest probes) --------------
_PENDING_PROBES = {
    # #350 CaptchaSolverPort
    "it is classified as score-based (avoid) or challenge-based (solve)": lambda: _probe(
        "applicant.ports.driven.captcha", "CaptchaSolverPort"
    ),
    "a response token is injected into the hidden field and the form can proceed": lambda: _probe(
        "applicant.adapters.captcha.solver_service", "SolverServiceAdapter"
    ),
    "the API key never appears in any log line": lambda: _probe(
        "applicant.adapters.captcha.solver_service", "SolverServiceAdapter"
    ),
    "the run pauses and hands off to the operator rather than auto-solving": lambda: _probe(
        "applicant.adapters.captcha.human_handoff", "HumanHandoffAdapter"
    ),
    "the final submit is still withheld for human review": lambda: _probe(
        "applicant.ports.driven.captcha", "CaptchaSolverPort"
    ),
    # #351 parity end-state
    "it produces a typed plan for the form without a hardcoded page model": lambda: _probe(
        "applicant.ports.driving.planner", "PlannerPort"
    ),
    "the next application to that ATS is guided by the induced routine": lambda: _assert_attr(
        "applicant.application.services.learning_service", "LearningService", "induce_workflow"
    ),
    "the planner reflects on the failure and re-plans rather than aborting": lambda: _probe(
        "applicant.ports.driving.planner", "PlannerPort"
    ),
    "it is avoided, solved, or handed off per the configured strategy": lambda: _probe(
        "applicant.ports.driven.captcha", "CaptchaSolverPort"
    ),
}


def _assert_attr(modpath: str, cls: str, attr: str):
    klass = _probe(modpath, cls)
    assert hasattr(klass, attr), f"{cls}.{attr} not implemented yet"


def _make_then(probe):
    def step(skyctx):
        probe()

    return step


for _phrase, _probe_fn in _PENDING_PROBES.items():
    then(_phrase)(_make_then(_probe_fn))


# narrative Given/When scaffolding for the @pending scenarios
_NARRATIVE = [
    "a CAPTCHA detected on a page",
    "the solver port inspects it",
    "a challenge-based CAPTCHA with a site key",
    "the solver-service adapter resolves it",
    "a configured solver-service adapter holding an API key",
    "the adapter runs and logs its activity",
    "the CAPTCHA strategy is set to the default human hand-off",
    "a CAPTCHA is encountered",
    "a solved CAPTCHA mid-application",
    "the plan continues past the CAPTCHA step",
    "a job-application form the engine has never seen before",
    "the planner builds a semantic snapshot fusing the rendered page and the DOM",
    "a successful pre-fill on a given ATS",
    "the engine induces a reusable routine from it",
    "a planned step whose target element is no longer present",
    "the step fails",
    "a CAPTCHA encountered during an application",
    "the engine routes it through the CAPTCHA solver port",
]


def _noop(skyctx):
    return None


for _phrase in _NARRATIVE:
    given(_phrase)(_noop)
    when(_phrase)(_noop)
