"""Hermetic tests for the SmartTierRouter (FR-LLM-3/4 extension).

All tier metadata is derived from the ladder configuration and provider profiles;
no network calls are needed.  Covers: cost-based routing, capability detection,
complexity estimation, and edge cases (no fitting tier, empty ladder).
"""

from __future__ import annotations

import pytest

from applicant.adapters.llm.tier_router import (
    SmartTierRouter,
    _build_tier_profiles,
    _estimate_complexity,
    _estimate_tokens,
    _find_cheapest_fitting,
)
from applicant.ports.driven.llm import ChatMessage, TierConfig, TierLadder

# ---------------------------------------------------------------------------
# Ladder fixtures
# ---------------------------------------------------------------------------

def _local_ladder() -> TierLadder:
    """A hybrid ladder: L1 = Ollama (local/cheap), L2 = OpenAI cloud."""
    return TierLadder(
        tiers=[
            TierConfig(
                provider="ollama",
                base_url="http://localhost:11434",
                model="llama3.1:8b",
                context_window=8192,
            ),
            TierConfig(
                provider="openai",
                base_url="https://api.openai.com/v1",
                model="gpt-4o-mini",
                api_key="sk-test",
                context_window=128_000,
            ),
        ]
    )


def _cloud_only_ladder() -> TierLadder:
    """A single-tier cloud ladder (no local model)."""
    return TierLadder(
        tiers=[
            TierConfig(
                provider="openai",
                base_url="https://api.openai.com/v1",
                model="gpt-4o-mini",
                api_key="sk-test",
                context_window=128_000,
            ),
        ]
    )


def _multi_tier_ladder() -> TierLadder:
    """A three-tier ladder: local cheap, cloud mid, cloud big."""
    return TierLadder(
        tiers=[
            TierConfig(
                provider="ollama",
                base_url="http://localhost:11434",
                model="llama3.1:8b",
                context_window=8192,
            ),
            TierConfig(
                provider="openai",
                base_url="https://api.openai.com/v1",
                model="gpt-4o-mini",
                api_key="sk-test",
                context_window=128_000,
            ),
            TierConfig(
                provider="openai",
                base_url="https://api.openai.com/v1",
                model="gpt-4o",
                api_key="sk-test",
                context_window=200_000,
            ),
        ]
    )


# ---------------------------------------------------------------------------
# Token / complexity estimation
# ---------------------------------------------------------------------------

def test_estimate_tokens_short():
    msgs = [ChatMessage(role="user", content="hello")]
    # len("user") + len("hello") = 4 + 5 = 9; 9 // 4 = 2
    assert _estimate_tokens(msgs) == 2


def test_estimate_tokens_long():
    msgs = [ChatMessage(role="user", content="x" * 4000)]
    assert _estimate_tokens(msgs) == 1001  # (3 + 4000) // 4 = 1000.75 → 1000


def test_estimate_complexity_simple():
    msgs = [ChatMessage(role="user", content="hi")]
    assert _estimate_complexity(msgs) == "simple"


def test_estimate_complexity_moderate():
    msgs = [ChatMessage(role="user", content="x" * 2000)]
    assert _estimate_complexity(msgs) == "moderate"


def test_estimate_complexity_complex():
    msgs = [ChatMessage(role="user", content="x" * 8000)]
    assert _estimate_complexity(msgs) == "complex"


# ---------------------------------------------------------------------------
# Tier profile metadata
# ---------------------------------------------------------------------------

def test_build_profiles_ollama_local():
    ladder = _local_ladder()
    profiles = _build_tier_profiles(ladder)
    assert len(profiles) == 2
    # L1 = Ollama
    assert profiles[0].cost_score == 0.0
    assert profiles[0].latency_score == 0.3
    assert profiles[0].supports_tools is False
    assert profiles[0].supports_structured_output is False
    assert profiles[0].provider == "ollama"
    assert profiles[0].model == "llama3.1:8b"
    # L2 = OpenAI
    assert profiles[1].cost_score == 1.0
    assert profiles[1].latency_score == 1.0
    assert profiles[1].supports_tools is True
    assert profiles[1].supports_structured_output is True
    assert profiles[1].provider == "openai"
    assert profiles[1].model == "gpt-4o-mini"


def test_build_profiles_cloud_only():
    ladder = _cloud_only_ladder()
    profiles = _build_tier_profiles(ladder)
    assert len(profiles) == 1
    assert profiles[0].cost_score == 1.0
    assert profiles[0].supports_tools is True
    assert profiles[0].supports_structured_output is True


# ---------------------------------------------------------------------------
# Cheapest fitting tier selection
# ---------------------------------------------------------------------------

def test_cheapest_fitting_simple_request():
    """A simple request should route to the free (local) tier."""
    ladder = _local_ladder()
    profiles = _build_tier_profiles(ladder)
    idx = _find_cheapest_fitting(profiles, required_tokens=100)
    assert idx == 0  # Ollama: cost_score=0, fits in 8192


def test_cheapest_fitting_requires_tools():
    """A request needing tool calling must skip the local tier."""
    ladder = _local_ladder()
    profiles = _build_tier_profiles(ladder)
    idx = _find_cheapest_fitting(profiles, required_tokens=100, needs_tools=True)
    assert idx == 1  # OpenAI: cost_score=1, supports tools


def test_cheapest_fitting_requires_structured():
    """A request needing structured output must skip the local tier."""
    ladder = _local_ladder()
    profiles = _build_tier_profiles(ladder)
    idx = _find_cheapest_fitting(profiles, required_tokens=100, needs_structured=True)
    assert idx == 1  # OpenAI: supports structured output


def test_cheapest_fitting_context_overflow_local():
    """A prompt exceeding the local tier's context window must route to cloud."""
    ladder = _local_ladder()
    profiles = _build_tier_profiles(ladder)
    # Local window = 8192 tokens, request = 10000 tokens
    idx = _find_cheapest_fitting(profiles, required_tokens=10_000)
    assert idx == 1  # OpenAI: 128k window


def test_cheapest_fitting_no_tier_fits():
    """When no tier has a large enough context window, return None."""
    ladder = TierLadder(
        tiers=[
            TierConfig(provider="ollama", base_url="http://localhost:11434", model="m", context_window=100),
        ]
    )
    profiles = _build_tier_profiles(ladder)
    idx = _find_cheapest_fitting(profiles, required_tokens=10_000)
    assert idx is None


def test_cheapest_fitting_tool_but_no_tool_support():
    """When tools are needed but NO tier supports them, return None."""
    ladder = TierLadder(
        tiers=[
            TierConfig(provider="ollama", base_url="http://localhost:11434", model="m", context_window=100_000),
        ]
    )
    profiles = _build_tier_profiles(ladder)
    idx = _find_cheapest_fitting(profiles, required_tokens=100, needs_tools=True)
    assert idx is None


# ---------------------------------------------------------------------------
# SmartTierRouter integration
# ---------------------------------------------------------------------------

def test_select_tier_simple_local(local_router):
    """A simple text-only prompt routes to L1 (local/cheap)."""
    msgs = [ChatMessage(role="user", content="hello")]
    decision = local_router.select_tier(msgs)
    assert decision.start_tier == 1
    assert "ollama" in decision.rationale
    assert "cost=0.0" in decision.rationale


@pytest.fixture
def local_router():
    return SmartTierRouter(ladder=_local_ladder())


def test_select_tier_needs_tools(local_router):
    """A tool-capable request routes to L2 (cloud)."""
    msgs = [ChatMessage(role="user", content="find companies")]
    tools = [{"type": "function", "function": {"name": "search", "parameters": {}}}]
    decision = local_router.select_tier(msgs, tools=tools)
    assert decision.start_tier == 2
    assert "tool calling" in decision.rationale


def test_select_tier_needs_structured(local_router):
    """A structured-output request routes to L2 (cloud)."""
    msgs = [ChatMessage(role="user", content="extract data")]
    schema = {"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}}}
    decision = local_router.select_tier(msgs, json_schema=schema)
    assert decision.start_tier == 2
    assert "structured output" in decision.rationale


def test_select_tier_cloud_only(cloud_router):
    """A single-tier cloud ladder always routes to L1."""
    msgs = [ChatMessage(role="user", content="hi")]
    decision = cloud_router.select_tier(msgs)
    assert decision.start_tier == 1
    assert "openai" in decision.rationale


@pytest.fixture
def cloud_router():
    return SmartTierRouter(ladder=_cloud_only_ladder())


def test_select_tier_default_fallback_no_fitting():
    """When no tier fits, the router falls back to default_start."""
    ladder = TierLadder(
        tiers=[
            TierConfig(provider="ollama", base_url="http://localhost:11434", model="m", context_window=100),
        ]
    )
    router = SmartTierRouter(ladder=ladder)
    msgs = [ChatMessage(role="user", content="x" * 4000)]  # ~1000 tokens
    decision = router.select_tier(msgs, default_start=1)
    assert decision.start_tier == 1
    assert "no tier fits" in decision.rationale


def test_select_tier_complex_prompt_stays_local_if_fits():
    """A complex prompt that fits the local window stays on the free tier."""
    ladder = _local_ladder()
    router = SmartTierRouter(ladder=ladder)
    msgs = [ChatMessage(role="user", content="x" * 6000)]  # ~1500 tokens, still fits 8192
    decision = router.select_tier(msgs)
    assert decision.start_tier == 1  # local fits and is cheapest


def test_select_tier_multi_tier_prefers_cheapest_cloud_for_tools():
    """With three tiers, tools still route to the cheapest cloud model (L2, not L3)."""
    ladder = _multi_tier_ladder()
    router = SmartTierRouter(ladder=ladder)
    msgs = [ChatMessage(role="user", content="search jobs")]
    tools = [{"type": "function", "function": {"name": "search", "parameters": {}}}]
    decision = router.select_tier(msgs, tools=tools)
    # L2 (gpt-4o-mini) is cheaper than L3 (gpt-4o) and supports tools.
    assert decision.start_tier == 2
    assert "gpt-4o-mini" in decision.rationale


def test_describe_tiers(local_router):
    """describe_tiers returns metadata for every configured tier."""
    profiles = local_router.describe_tiers()
    assert len(profiles) == 2
    assert profiles[0].provider == "ollama"
    assert profiles[0].model == "llama3.1:8b"
    assert profiles[1].provider == "openai"
    assert profiles[1].model == "gpt-4o-mini"


def test_router_accepts_empty_messages(local_router):
    """An empty message list is handled gracefully (routes to L1)."""
    decision = local_router.select_tier([])
    assert decision.start_tier == 1


def test_router_with_both_tools_and_structured(local_router):
    """When both tools and structured output are required, route to capable tier."""
    msgs = [ChatMessage(role="user", content="extract companies from search")]
    tools = [{"type": "function", "function": {"name": "search", "parameters": {}}}]
    schema = {"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}}}
    decision = local_router.select_tier(msgs, json_schema=schema, tools=tools)
    assert decision.start_tier == 2
    assert "tool calling" in decision.rationale
    assert "structured output" in decision.rationale


def test_rationale_includes_estimation(local_router):
    """The rationale includes the estimated token count."""
    msgs = [ChatMessage(role="user", content="hello world")]
    decision = local_router.select_tier(msgs)
    assert "tokens estimated" in decision.rationale
