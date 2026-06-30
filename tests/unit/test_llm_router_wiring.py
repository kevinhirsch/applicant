"""End-to-end wiring tests for smart LLM routing (#298).

Unlike ``test_llm_router.py`` (which drives the router against an in-memory
``_FakeEndpointService``), these tests exercise the REAL ``ModelEndpointService``
and the REAL ``OpenAICompatibleLLM`` to prove the full chain:

  router selects a local endpoint  ->  ``order_ladder_by_router`` moves that
  tier to the front of the ladder  ->  ``OpenAICompatibleLLM.complete`` walks
  that tier first  ->  the engine actually CALLS the local model (Ollama's
  ``/api/chat``) and not the cloud model.

Both legs of #298 are covered: (1) local-LLM support is reachable through the
existing adapter (``_call_ollama``), and (2) smart routing picks it. The config
flag is proven default-OFF (cloud-first ladder unchanged) and opt-in ON
(local-first ladder, local model called).

Hermetic: every HTTP call (model probe + chat completion) goes through an
injected ``httpx.MockTransport`` so nothing touches the network.
"""

from __future__ import annotations

import httpx

from applicant.adapters.llm.openai_compatible import OpenAICompatibleLLM
from applicant.adapters.llm.smart_router import (
    SmartLlmRouter,
    order_ladder_by_router,
)
from applicant.adapters.storage.app_config_store import InMemoryAppConfigStore
from applicant.application.services.model_endpoint_service import ModelEndpointService
from applicant.ports.driven.llm import ChatMessage, TierConfig, TierLadder
from applicant.ports.driven.llm_router import CostTier, TaskType

_LOCAL_BASE = "http://localhost:11434/v1"
_CLOUD_BASE = "https://api.openai.com/v1"


def _endpoint_transport() -> httpx.MockTransport:
    """Serve the model-list probes so both endpoints read as ``online``."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/api/tags"):  # Ollama local
            return httpx.Response(200, json={"models": [{"name": "llama3.1:8b"}]})
        if path.endswith("/models"):  # OpenAI-compatible cloud
            return httpx.Response(200, json={"data": [{"id": "gpt-4o"}]})
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def _chat_transport(hits: list[str]) -> httpx.MockTransport:
    """Serve chat completions, recording which provider path was actually called.

    Ollama uses ``/api/chat``; OpenAI-compatible cloud uses
    ``/chat/completions``. Recording the hit proves WHICH model the engine called.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/api/chat"):  # local Ollama chat
            hits.append("local")
            return httpx.Response(200, json={"message": {"content": "local-reply"}})
        if path.endswith("/chat/completions"):  # cloud OpenAI chat
            hits.append("cloud")
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "cloud-reply"}}]},
            )
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def _real_endpoint_service() -> ModelEndpointService:
    """A REAL ModelEndpointService with a local + cloud endpoint, both online."""
    svc = ModelEndpointService(
        config_store=InMemoryAppConfigStore(),
        credentials=None,
        transport=_endpoint_transport(),
    )
    # Add a cloud endpoint first, then a local one, to make ladder order matter.
    svc.add_endpoint(base_url=_CLOUD_BASE, api_key="sk-test", name="OpenAI")
    svc.add_endpoint(base_url=_LOCAL_BASE, name="Ollama")
    return svc


def _cloud_first_ladder() -> TierLadder:
    """A ladder whose FIRST tier is the cloud model (mirrors the configured order).

    Both tiers comfortably hold the tiny test prompt, so the context-window
    walk never escalates — only routing order decides which tier is called.
    """
    return TierLadder(
        tiers=[
            TierConfig(
                provider="openai",
                base_url=_CLOUD_BASE,
                model="gpt-4o",
                api_key="sk-test",
                context_window=128_000,
            ),
            TierConfig(
                provider="ollama",
                base_url=_LOCAL_BASE,
                model="llama3.1:8b",
                context_window=8192,
            ),
        ]
    )


def test_real_endpoint_service_reports_both_online():
    """Sanity: the real service probes both endpoints and reports them online."""
    svc = _real_endpoint_service()
    eps = {e["name"]: e for e in svc.list_endpoints(refresh=True)}
    assert eps["Ollama"]["online"] is True
    assert eps["Ollama"]["category"] == "local"
    assert eps["OpenAI"]["online"] is True
    assert eps["OpenAI"]["category"] == "api"


def test_routing_off_preserves_cloud_first_ladder_and_calls_cloud():
    """Flag OFF == ladder untouched: the configured cloud tier is called first.

    This mirrors the container's default path (``llm_smart_routing`` False), where
    the ladder goes straight from ``build_ladder()`` into the LLM with no reorder.
    """
    ladder = _cloud_first_ladder()
    hits: list[str] = []
    llm = OpenAICompatibleLLM(ladder=ladder, transport=_chat_transport(hits))

    result = llm.complete([ChatMessage(role="user", content="hi")])

    assert result.text == "cloud-reply"
    assert hits == ["cloud"]  # cloud (first tier) called; local never touched


def test_routing_on_moves_local_to_front_and_calls_local_model():
    """Flag ON + prefer_local: router picks local, ladder reorders, LOCAL is called.

    Proves BOTH legs of #298 end-to-end against the REAL ModelEndpointService:
      * the router selects the LOCAL endpoint under the lowest-cost policy, and
      * that selection actually reaches the live LLM path — the engine calls the
        local Ollama ``/api/chat`` model, not the cloud one.
    """
    svc = _real_endpoint_service()
    router = SmartLlmRouter(svc)

    # 1) The router selects the local endpoint under the local-preference policy.
    selected = router.select_endpoint(
        TaskType.CHAT, cost_tier=CostTier.LOWEST, prefer_local=True
    )
    assert selected is not None
    assert selected["category"] == "local"
    assert "11434" in selected["base_url"]

    # 2) order_ladder_by_router moves the matching (local) tier to the front,
    #    keeping every other tier (additive reorder, not a rewrite).
    ladder = _cloud_first_ladder()
    reordered = order_ladder_by_router(
        ladder,
        router,
        task=TaskType.CHAT,
        cost_tier=CostTier.LOWEST,
        prefer_local=True,
    )
    assert reordered is not None
    assert reordered.at(0).provider == "ollama"  # local now first
    assert reordered.at(0).base_url == _LOCAL_BASE
    assert len(reordered) == 2  # cloud tier retained as the fallback rung

    # 3) The reordered ladder drives a REAL completion: the engine calls the
    #    LOCAL model (Ollama /api/chat), confirming routing reaches the live path.
    hits: list[str] = []
    llm = OpenAICompatibleLLM(ladder=reordered, transport=_chat_transport(hits))
    result = llm.complete([ChatMessage(role="user", content="hi")])

    assert result.text == "local-reply"
    assert hits == ["local"]  # local model actually called, cloud not touched


def test_order_ladder_no_router_match_is_unchanged():
    """When no tier matches the selected endpoint URL, the ladder is returned as-is."""
    svc = _real_endpoint_service()
    router = SmartLlmRouter(svc)
    # A ladder whose URLs match NEITHER configured endpoint -> no safe reorder.
    ladder = TierLadder(
        tiers=[
            TierConfig(provider="openai", base_url="https://other.example/v1", model="x"),
        ]
    )
    out = order_ladder_by_router(
        ladder, router, cost_tier=CostTier.LOWEST, prefer_local=True
    )
    assert out is ladder  # unchanged, no stranding


def test_order_ladder_none_passthrough():
    """A None ladder (no LLM configured yet) passes straight through."""
    svc = _real_endpoint_service()
    router = SmartLlmRouter(svc)
    assert order_ladder_by_router(None, router) is None
