"""Hermetic tests for the CaptchaSolverPort plumbing (issue #350).

Covers, with NO live key and NO browser/network:
  * the port contract (the adapters + composite satisfy CaptchaSolverPort),
  * avoid-vs-service classification,
  * token injection for reCAPTCHA v2 / hCaptcha / Turnstile (a MOCK solver returns a
    token → assert it is injected into the right hidden field + the callback fires),
  * human-handoff fallback when the solver is off / returns nothing / fails,
  * the secret (CAPTCHA_API_KEY) never appears in any log line,
  * the pre-fill captcha stop-boundary remains the backstop with the default config
    (byte-for-byte today's hand-off), and is never bypassed for account-create /
    final-submit.

The ONLY part not exercised here is the live third-party HTTP call inside
``HttpTokenSolver.__call__`` — that needs a real key and is mocked away.
"""

from __future__ import annotations

import logging

import pytest

from applicant.adapters.captcha import (
    BehavioralAvoidanceStrategy,
    CaptchaSolver,
    HumanHandoffAdapter,
    SolverServiceAdapter,
)
from applicant.adapters.captcha.context import build_captcha_context
from applicant.adapters.captcha.solver_service import HttpTokenSolver
from applicant.ports.driven.captcha import (
    CaptchaContext,
    CaptchaDisposition,
    CaptchaKind,
    CaptchaOutcome,
    CaptchaSolverPort,
)


# --- test doubles -----------------------------------------------------------
class RecordingInjector:
    """A fake TokenInjector that records the field/token/callback it was asked to write."""

    def __init__(self, *, succeed: bool = True) -> None:
        self.calls: list[dict] = []
        self._succeed = succeed

    def inject_captcha_token(self, *, field: str, token: str, callback: str = "") -> bool:
        self.calls.append({"field": field, "token": token, "callback": callback})
        return self._succeed


def _mock_solver(token):
    def solver(kind, site_key, page_url):
        return token

    return solver


# --- port contract ----------------------------------------------------------
@pytest.mark.parametrize(
    "adapter",
    [
        BehavioralAvoidanceStrategy(),
        HumanHandoffAdapter(),
        SolverServiceAdapter(),
        CaptchaSolver(),
    ],
)
def test_adapters_satisfy_the_port_contract(adapter):
    assert isinstance(adapter, CaptchaSolverPort)
    # classify + resolve are present and return the right types.
    ctx = CaptchaContext(url="https://x/y", kind=CaptchaKind.UNKNOWN)
    assert isinstance(adapter.classify(ctx), CaptchaDisposition)
    assert isinstance(adapter.resolve(ctx), CaptchaOutcome)


# --- avoid vs service classification ----------------------------------------
def test_score_based_captcha_is_avoided_not_solved():
    avoid = BehavioralAvoidanceStrategy()
    for kind in (CaptchaKind.RECAPTCHA_V3, CaptchaKind.TURNSTILE):
        ctx = CaptchaContext(url="https://x", kind=kind)
        assert avoid.classify(ctx) is CaptchaDisposition.AVOID
        out = avoid.resolve(ctx)
        assert out.disposition is CaptchaDisposition.AVOID
        assert out.solved is False  # avoidance never produces a token


def test_interactive_captcha_with_key_classifies_as_solve_when_configured():
    svc = SolverServiceAdapter(solver=_mock_solver("tok"), injector=RecordingInjector())
    ctx = CaptchaContext(url="https://x", kind=CaptchaKind.HCAPTCHA, site_key="sk")
    assert svc.classify(ctx) is CaptchaDisposition.SOLVE


def test_interactive_captcha_without_key_hands_off():
    svc = SolverServiceAdapter(solver=_mock_solver("tok"), injector=RecordingInjector())
    ctx = CaptchaContext(url="https://x", kind=CaptchaKind.HCAPTCHA, site_key="")
    assert svc.classify(ctx) is CaptchaDisposition.HANDOFF


def test_unconfigured_service_hands_off():
    svc = SolverServiceAdapter()  # no solver, no key
    assert svc.is_configured() is False
    ctx = CaptchaContext(url="https://x", kind=CaptchaKind.RECAPTCHA_V2, site_key="sk")
    assert svc.classify(ctx) is CaptchaDisposition.HANDOFF
    assert svc.resolve(ctx).disposition is CaptchaDisposition.HANDOFF


def test_composite_human_strategy_always_hands_off():
    composite = CaptchaSolver(strategy="human")
    for kind in CaptchaKind:
        ctx = CaptchaContext(url="https://x", kind=kind, site_key="sk")
        assert composite.classify(ctx) is CaptchaDisposition.HANDOFF
        assert composite.resolve(ctx).solved is False


def test_composite_avoid_strategy_avoids_score_solves_nothing():
    composite = CaptchaSolver(strategy="avoid")
    assert (
        composite.classify(CaptchaContext(url="x", kind=CaptchaKind.TURNSTILE))
        is CaptchaDisposition.AVOID
    )
    # An interactive challenge under "avoid" still hands off (no solver wired).
    assert (
        composite.classify(
            CaptchaContext(url="x", kind=CaptchaKind.HCAPTCHA, site_key="sk")
        )
        is CaptchaDisposition.HANDOFF
    )


# --- real telemetry counters, never fabricated (dark-engine audit #67) ------
def test_stats_start_at_zero_and_expose_the_effective_configuration():
    composite = CaptchaSolver(strategy="avoid")
    stats = composite.stats()
    assert stats["strategy"] == "avoid"
    assert stats["service_configured"] is False
    assert stats["attempts"] == 0
    assert stats["solved"] == 0
    assert stats["avoided"] == 0
    assert stats["handed_off"] == 0


def test_stats_tally_avoided_outcomes():
    composite = CaptchaSolver(strategy="avoid")
    composite.resolve(CaptchaContext(url="x", kind=CaptchaKind.TURNSTILE))
    composite.resolve(CaptchaContext(url="x", kind=CaptchaKind.RECAPTCHA_V3))
    stats = composite.stats()
    assert stats["attempts"] == 2
    assert stats["avoided"] == 2
    assert stats["solved"] == 0
    assert stats["handed_off"] == 0


def test_stats_tally_handed_off_outcomes_under_the_default_strategy():
    composite = CaptchaSolver(strategy="human")
    composite.resolve(CaptchaContext(url="x", kind=CaptchaKind.HCAPTCHA, site_key="sk"))
    stats = composite.stats()
    assert stats["attempts"] == 1
    assert stats["handed_off"] == 1
    assert stats["solved"] == 0
    assert stats["avoided"] == 0


def test_stats_tally_solved_outcomes_under_the_service_strategy():
    svc = SolverServiceAdapter(solver=_mock_solver("tok"), injector=RecordingInjector())
    composite = CaptchaSolver(strategy="service", service=svc)
    composite.resolve(CaptchaContext(url="x", kind=CaptchaKind.HCAPTCHA, site_key="sk"))
    stats = composite.stats()
    assert stats["service_configured"] is True
    assert stats["attempts"] == 1
    assert stats["solved"] == 1
    assert stats["handed_off"] == 0
    assert stats["avoided"] == 0


# --- token injection for the three interactive families ---------------------
@pytest.mark.parametrize(
    ("kind", "expected_field"),
    [
        (CaptchaKind.RECAPTCHA_V2, "g-recaptcha-response"),
        (CaptchaKind.HCAPTCHA, "h-captcha-response"),
        (CaptchaKind.TURNSTILE, "cf-turnstile-response"),
    ],
)
def test_token_injected_into_the_right_hidden_field_and_callback_fires(kind, expected_field):
    injector = RecordingInjector()
    svc = SolverServiceAdapter(solver=_mock_solver("THE_TOKEN"), injector=injector)
    ctx = CaptchaContext(
        url="https://x",
        kind=kind,
        site_key="sk",
        response_field="",  # let the adapter pick the family default
        callback="onCaptchaSolved",
    )
    out = svc.resolve(ctx)
    assert out.solved is True
    assert out.disposition is CaptchaDisposition.SOLVE
    assert len(injector.calls) == 1
    call = injector.calls[0]
    assert call["field"] == expected_field
    assert call["token"] == "THE_TOKEN"
    assert call["callback"] == "onCaptchaSolved"


def test_explicit_response_field_overrides_the_default():
    injector = RecordingInjector()
    svc = SolverServiceAdapter(solver=_mock_solver("t"), injector=injector)
    ctx = CaptchaContext(
        url="x", kind=CaptchaKind.RECAPTCHA_V2, site_key="sk", response_field="#custom"
    )
    assert svc.resolve(ctx).solved is True
    assert injector.calls[0]["field"] == "#custom"


# --- human-handoff fallback when solver off / failed ------------------------
def test_solver_returns_no_token_falls_back_to_handoff():
    svc = SolverServiceAdapter(solver=_mock_solver(None), injector=RecordingInjector())
    ctx = CaptchaContext(url="x", kind=CaptchaKind.HCAPTCHA, site_key="sk")
    out = svc.resolve(ctx)
    assert out.solved is False
    assert out.disposition is CaptchaDisposition.HANDOFF


def test_solver_raises_falls_back_to_handoff():
    def boom(kind, site_key, page_url):
        raise RuntimeError("solver down")

    svc = SolverServiceAdapter(solver=boom, injector=RecordingInjector())
    ctx = CaptchaContext(url="x", kind=CaptchaKind.RECAPTCHA_V2, site_key="sk")
    out = svc.resolve(ctx)
    assert out.solved is False
    assert out.disposition is CaptchaDisposition.HANDOFF


def test_injection_failure_falls_back_to_handoff():
    svc = SolverServiceAdapter(
        solver=_mock_solver("tok"), injector=RecordingInjector(succeed=False)
    )
    ctx = CaptchaContext(url="x", kind=CaptchaKind.HCAPTCHA, site_key="sk")
    out = svc.resolve(ctx)
    assert out.solved is False
    assert out.disposition is CaptchaDisposition.HANDOFF


# --- secret never appears in logs -------------------------------------------
def test_api_key_never_appears_in_logs(caplog):
    secret = "sk-SUPER-SECRET-CAPTCHA-KEY-12345"
    solver = HttpTokenSolver(api_key=secret, service="capsolver")
    svc = SolverServiceAdapter(solver=solver, injector=RecordingInjector(), api_key=secret)
    with caplog.at_level(logging.DEBUG):
        # Exercise the configured path (no real network → returns None → hand-off).
        ctx = CaptchaContext(url="https://x", kind=CaptchaKind.HCAPTCHA, site_key="sk")
        svc.resolve(ctx)
        # And the repr paths the secret could leak through.
        _ = repr(svc)
        _ = repr(solver)
        logging.getLogger(__name__).info("adapter=%r solver=%r", svc, solver)
    blob = "\n".join(r.getMessage() for r in caplog.records)
    assert secret not in blob
    assert secret not in repr(svc)
    assert secret not in repr(solver)
    assert "***" in repr(solver)


# --- context detection from page markup -------------------------------------
def test_context_builder_detects_families_and_site_key():
    class _State:
        def __init__(self, body, url="https://ats/apply"):
            self.body = body
            self.url = url

    rec2 = build_captcha_context(
        _State('<div class="g-recaptcha" data-sitekey="KEY2"></div>')
    )
    assert rec2.kind is CaptchaKind.RECAPTCHA_V2 and rec2.site_key == "KEY2"

    hc = build_captcha_context(
        _State('<div class="h-captcha" data-sitekey="HKEY"></div>')
    )
    assert hc.kind is CaptchaKind.HCAPTCHA and hc.site_key == "HKEY"

    ts = build_captcha_context(
        _State('<div class="cf-turnstile" data-sitekey="TKEY"></div>')
    )
    assert ts.kind is CaptchaKind.TURNSTILE and ts.site_key == "TKEY"

    v3 = build_captcha_context(
        _State('<script src="https://www.google.com/recaptcha/api.js?render=V3KEY">')
    )
    assert v3.kind is CaptchaKind.RECAPTCHA_V3 and v3.site_key == "V3KEY"

    none = build_captcha_context(_State("<form>no captcha here</form>"))
    assert none.kind is CaptchaKind.UNKNOWN


# --- the pre-fill wiring point: default = the existing hand-off backstop -----
class _State:
    def __init__(self, body, url="https://ats/apply"):
        self.body = body
        self.url = url


class _App:
    """Minimal app stub exposing only what ``_try_solve_captcha`` reads."""

    class _Id:
        def __str__(self):
            return "app-1"

    id = _Id()


def _bare_prefill(captcha_solver):
    """A PrefillService with only the captcha_solver wired (others are unused here)."""
    from applicant.application.services.prefill_service import PrefillService

    return PrefillService(
        storage=None,
        browser=None,
        detection=None,
        sandbox=None,
        credentials=None,
        captcha_solver=captcha_solver,
    )


def test_prefill_default_no_solver_does_not_resolve_captcha():
    """Default config (no solver) → _try_solve_captcha returns False, so the caller
    runs the EXISTING captcha stop-boundary hand-off — byte-for-byte today's behavior."""
    svc = _bare_prefill(captcha_solver=None)
    state = _State('<div class="h-captcha" data-sitekey="K"></div>')
    assert svc._try_solve_captcha(_App(), state) is False


def test_prefill_human_strategy_does_not_resolve_captcha():
    """Even with the composite wired, the default ``human`` strategy hands off."""
    svc = _bare_prefill(captcha_solver=CaptchaSolver(strategy="human"))
    state = _State('<div class="h-captcha" data-sitekey="K"></div>')
    assert svc._try_solve_captcha(_App(), state) is False


def test_prefill_avoid_strategy_continues_on_score_based():
    """Opt-in avoid → a score-based captcha is resolved (proceed) so the loop continues."""
    svc = _bare_prefill(captcha_solver=CaptchaSolver(strategy="avoid"))
    state = _State('<script src="https://www.google.com/recaptcha/api.js?render=V3">')
    assert svc._try_solve_captcha(_App(), state) is True


def test_prefill_service_strategy_solves_and_continues():
    """Opt-in service + a mock solver → an interactive captcha is solved/injected and
    the loop continues."""
    svc_adapter = SolverServiceAdapter(
        solver=_mock_solver("tok"), injector=RecordingInjector()
    )
    composite = CaptchaSolver(strategy="service", service=svc_adapter)
    svc = _bare_prefill(captcha_solver=composite)
    state = _State('<div class="h-captcha" data-sitekey="K"></div>')
    assert svc._try_solve_captcha(_App(), state) is True


def test_prefill_service_strategy_failed_solve_falls_back_to_handoff():
    """Opt-in service but the solver fails → _try_solve_captcha returns False → hand-off."""
    svc_adapter = SolverServiceAdapter(
        solver=_mock_solver(None), injector=RecordingInjector()
    )
    composite = CaptchaSolver(strategy="service", service=svc_adapter)
    svc = _bare_prefill(captcha_solver=composite)
    state = _State('<div class="h-captcha" data-sitekey="K"></div>')
    assert svc._try_solve_captcha(_App(), state) is False


def test_solver_never_resolves_a_non_captcha_stop():
    """The solver is only consulted for the captcha stop reason — _try_solve_captcha is
    never invoked for account_create / final_submit (those branches don't call it).
    Asserted structurally: an UNKNOWN captcha (e.g. a stray marker) still hands off, so
    the solver can never turn a non-captcha gate into a 'continue'."""
    svc = _bare_prefill(captcha_solver=CaptchaSolver(strategy="service"))
    state = _State("<form>account creation, no captcha widget</form>")
    assert svc._try_solve_captcha(_App(), state) is False
