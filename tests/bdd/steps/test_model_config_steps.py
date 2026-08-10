"""Step bindings for EPIC MODEL-CONFIG — per-use-case model configuration.

Real regression coverage (no ``@pending``): asserts against the actual
``SetupService`` per-use-case binding API + the shared ``ModelEndpointService``
registry through in-memory adapters (hexagonal — no UI internals, no network; the
model-endpoint probe is disabled). Mirrors production: both services share one
config store, so a saved endpoint is resolvable as a bound use case's primary tier.
"""

from __future__ import annotations

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from applicant.adapters.storage.app_config_store import InMemoryAppConfigStore
from applicant.app.config import llm_use_case_keys
from applicant.application.services.model_endpoint_service import ModelEndpointService
from applicant.application.services.setup_service import SetupService
from applicant.ports.driving.setup_wizard import TierSettings

scenarios("../features/enhancements/model_config_per_use_case.feature")


@pytest.fixture
def mcx() -> dict:
    return {}


def _resolver(endpoints: ModelEndpointService):
    def _resolve(endpoint_id: str):
        rec = endpoints.get_endpoint(endpoint_id)
        if rec is None:
            return None
        return {
            "base_url": rec.get("base_url", ""),
            "api_key": endpoints._resolve_key(rec),
            "name": rec.get("name", ""),
        }

    return _resolve


@given("a setup service and model-endpoint registry sharing one config store")
def _stack(mcx):
    store = InMemoryAppConfigStore()
    mcx["setup"] = SetupService(config_store=store)
    mcx["endpoints"] = ModelEndpointService(config_store=store, credentials=None)


@given("the tier ladder is local qwen with a DeepSeek cloud fallback")
def _ladder(mcx):
    mcx["setup"].set_tiers(
        [
            TierSettings(
                provider="ollama", base_url="http://localhost:11434", model="qwen-local"
            ),
            TierSettings(
                provider="openai",
                base_url="https://api.deepseek.com/v1",
                model="deepseek-fallback",
                context_window=64000,
            ),
        ]
    )


@given("no per-use-case bindings are stored")
def _no_bindings(mcx):
    assert mcx["setup"].get_use_case_bindings() == {}


@given(parsers.parse('I add an OpenAI-compatible endpoint at "{base_url}"'))
def _add_endpoint(mcx, base_url):
    mcx["endpoint_id"] = mcx["endpoints"].add_endpoint(base_url=base_url, probe=False)["id"]


@given(
    parsers.parse(
        'I bind the "{use_case}" use case to that endpoint with model "{model}"'
    )
)
@when(
    parsers.parse(
        'I bind the "{use_case}" use case to that endpoint with model "{model}"'
    )
)
def _bind(mcx, use_case, model):
    mcx["setup"].set_use_case_binding(
        use_case, mode="endpoint", endpoint_id=mcx["endpoint_id"], model=model
    )


@when(parsers.parse('I resolve the ladder for the "{use_case}" use case'))
def _resolve(mcx, use_case):
    mcx["ladder"] = mcx["setup"].resolve_use_case_ladder(
        use_case, endpoint_resolver=_resolver(mcx["endpoints"])
    )


@when(parsers.parse('I reset the "{use_case}" use case to default'))
def _reset(mcx, use_case):
    mcx["setup"].clear_use_case_binding(use_case)


@then("it is exactly the shared tier ladder")
def _is_shared(mcx):
    assert [t.model for t in mcx["ladder"].tiers] == ["qwen-local", "deepseek-fallback"]


@then("every documented use case is listed as configurable")
def _all_listed(mcx):
    keys = llm_use_case_keys()
    assert {"scoring", "drafting_cover_letter", "chat", "embeddings"} <= set(keys)


@then(parsers.parse('the primary tier is "{model}" at that endpoint'))
def _primary(mcx, model):
    top = mcx["ladder"].tiers[0]
    assert top.model == model
    assert top.base_url == "https://openrouter.ai/api/v1"


@then("the shared ladder remains below it as the fallback")
def _fallback(mcx):
    assert [t.model for t in mcx["ladder"].tiers[1:]] == [
        "qwen-local",
        "deepseek-fallback",
    ]


@then(
    parsers.parse(
        'the "{use_case}" use case reports it is bound to that endpoint and model'
    )
)
def _reports(mcx, use_case):
    binding = mcx["setup"].get_use_case_binding(use_case)
    assert binding is not None
    assert binding["mode"] == "endpoint"
    assert binding["endpoint_id"] == mcx["endpoint_id"]
    assert binding["model"]


@then(parsers.parse('resolving the "{use_case}" ladder is exactly the shared tier ladder'))
def _resolves_shared(mcx, use_case):
    ladder = mcx["setup"].resolve_use_case_ladder(
        use_case, endpoint_resolver=_resolver(mcx["endpoints"])
    )
    assert [t.model for t in ladder.tiers] == ["qwen-local", "deepseek-fallback"]
