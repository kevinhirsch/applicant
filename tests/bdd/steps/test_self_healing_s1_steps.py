"""Step bindings for EPIC SELF-HEAL Slice S1 (remote-repairs-local LLM).

Grounds: `docs/adr/0008-autonomous-self-healing.md`, `docs/stories/self-healing.md#s1`,
`src/applicant/application/services/llm_wedge_detector.py`,
`src/applicant/adapters/llm/openai_compatible.py`.

Follows the canonical enhancement-spec pattern (see
`tests/bdd/steps/test_enh_t12_cua_steps.py`'s docstring):

* The scenario with NO `@pending` tag ("Inference escalates to remote when local
  is unreachable") is REAL regression coverage for behaviour that ships on this
  branch — it dispatches a completion through the actual tier-ladder adapter
  (`OpenAICompatibleLLM`) over a hermetic `httpx.MockTransport`, exactly the
  shape `tests/unit/test_llm_fallback_tier.py` already proves, and must pass
  today.
* The two `@pending`-tagged scenarios ("The remote-tier remediator restarts the
  wedged local model" / "Restart attempts are bounded and fail safe") describe
  the cross-box "restart the local vLLM host" action, which THIS SLICE
  explicitly does NOT build (flagged in ADR-0008 Consequences as "a genuine new
  build, not reuse", needing infra a separate vLLM-host watchdog owns). Their
  steps make an HONEST probe at the real target — a speculative import of the
  not-yet-built restart-action service — so each scenario is a genuine red,
  never `assert True`. `conftest.pytest_bdd_apply_tag` maps `@pending` to a
  non-strict xfail.
"""

from __future__ import annotations

import httpx
import pytest
from pytest_bdd import given, scenarios, then, when

from applicant.adapters.llm.openai_compatible import OpenAICompatibleLLM
from applicant.ports.driven.llm import ChatMessage, LLMLadderExhausted, TierConfig, TierLadder

scenarios("../features/self_healing/s1_remote_repairs_local.feature")


@pytest.fixture
def s1ctx() -> dict:
    return {}


# ===========================================================================
# GREEN — inference escalates to the remote fallback tier when local is down
# ===========================================================================
@given("the local vLLM endpoint is unreachable")
def local_endpoint_unreachable(s1ctx):
    def handler(request: httpx.Request) -> httpx.Response:
        if "deepseek" not in str(request.url):
            # The local API stays reachable-looking in a real wedge (it's the
            # generation that deadlocks) but any transport failure (connect
            # timeout, read timeout, refused connection) hits the SAME
            # `httpx.HTTPError` catch in `complete()` -- modeled here directly.
            raise httpx.ConnectTimeout("local vLLM endpoint unreachable (simulated)")
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "the remote fallback answered"}}]},
        )

    ladder = TierLadder(
        tiers=[
            TierConfig(
                provider="ollama",
                base_url="http://127.0.0.1:11434",
                model="qwen3.6:27b",
                context_window=32768,
            ),
            TierConfig(
                provider="openai",
                base_url="https://api.deepseek.com/v1",
                model="deepseek-chat",
                api_key="sk-fallback-test-key",
                context_window=65536,
            ),
        ]
    )
    s1ctx["llm"] = OpenAICompatibleLLM(ladder=ladder, transport=httpx.MockTransport(handler))


@when("a scoring or chat call is dispatched through the tier ladder")
def dispatch_through_ladder(s1ctx):
    try:
        s1ctx["result"] = s1ctx["llm"].complete(
            [ChatMessage(role="user", content="score this posting")]
        )
        s1ctx["exc"] = None
    except LLMLadderExhausted as exc:  # pragma: no cover - only on a real regression
        s1ctx["result"] = None
        s1ctx["exc"] = exc


@then("the call escalates to the remote fallback tier")
def call_escalates_to_fallback(s1ctx):
    assert s1ctx["exc"] is None, f"ladder exhausted instead of escalating: {s1ctx['exc']}"
    assert s1ctx["result"].tier == 2, "expected the SECOND (fallback) tier to answer"


@then("the caller receives a valid result without LLMLadderExhausted being raised")
def receives_valid_result(s1ctx):
    assert s1ctx["exc"] is None
    assert s1ctx["result"] is not None
    assert s1ctx["result"].text == "the remote fallback answered"


# ===========================================================================
# @pending — cross-box "restart the wedged local model" action (OUT OF SCOPE
# for this slice; see the module docstring and ADR-0008 Consequences).
# ===========================================================================
@given("the local vLLM endpoint has been reported unreachable for more than one detector cycle")
def endpoint_unreachable_for_cycles(s1ctx):
    s1ctx["needs_remote_remediator"] = True


@when(
    "the remediator, itself running on the remote tier since local is down, "
    "diagnoses the endpoint"
)
def remediator_diagnoses_endpoint(s1ctx):
    # HONEST PROBE: the remote-tier remediator that diagnoses AND restarts the
    # local model service is the scoped single-service-restart control-plane
    # channel ADR-0008 names as "a genuine new build, not reuse" (Consequences
    # §, gap #1) -- nothing in the stack can restart one named service short of
    # the updater sidecar's full-stack `update.sh --apply`. No such narrower
    # service exists yet, so this import is a real, not simulated, failure.
    import importlib

    importlib.import_module("applicant.application.services.local_model_restart_service")


@then("it issues a bounded restart request against the local model service")
def issues_bounded_restart_request(s1ctx):
    raise AssertionError(
        "no local-model restart action exists yet -- explicitly out of scope for S1"
    )


@then("the local endpoint eventually reports online again")
def endpoint_reports_online_again(s1ctx):
    raise AssertionError(
        "no restart-driven recovery exists yet -- explicitly out of scope for S1"
    )


@then("zero human action was required")
def zero_human_action_required(s1ctx):
    raise AssertionError(
        "no autonomous local-model restart path exists yet -- explicitly out of scope for S1"
    )


@then("an audit entry links the detection, the restart action, and the recovery")
def audit_links_detection_action_recovery(s1ctx):
    raise AssertionError(
        "no restart action exists yet to link in the audit trail -- out of scope for S1"
    )


# ===========================================================================
# @pending — restart attempts bounded + fail-safe (same out-of-scope gap)
# ===========================================================================
@given("the local model restart action has failed its bounded retry budget")
def restart_action_budget_exhausted(s1ctx):
    s1ctx["needs_restart_action"] = True


@when("the budget is exhausted")
def restart_budget_exhausted_event(s1ctx):
    # HONEST PROBE: same not-yet-built restart-action service as above.
    import importlib

    importlib.import_module("applicant.application.services.local_model_restart_service")


@then("the system stops attempting restarts")
def stops_attempting_restarts(s1ctx):
    raise AssertionError(
        "no bounded restart-attempt budget exists yet -- explicitly out of scope for S1"
    )


@then("it alerts via the existing notification path")
def restart_alerts_via_notification(s1ctx):
    raise AssertionError(
        "no restart-exhaustion alert exists yet -- explicitly out of scope for S1"
    )


@then("it continues serving inference from the remote fallback tier in the meantime")
def continues_serving_from_fallback(s1ctx):
    raise AssertionError(
        "no restart-action continuity check exists yet -- explicitly out of scope for S1"
    )
