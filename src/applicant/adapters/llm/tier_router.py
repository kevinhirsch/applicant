"""Smart tier router adapter (FR-LLM-3/4 extension).

Selects the optimal starting tier for an LLM completion based on cost, latency,
and capability heuristics.  Designed to be wired as an optional dependency of
any service that calls :meth:`LLMPort.complete` — when not wired, callers use
the existing ``start_tier=1`` behaviour unchanged.

Analysis dimensions
-------------------
* **Cost** — local (Ollama) tiers cost 0; cloud tiers cost 1+. Simple requests
  (short prompts, no schema, no tools) are routed to the cheapest tier that
  fits the context window.
* **Latency** — local models avoid a network round-trip for short prompts but
  may be slower for very long generations. The router prefers local tiers for
  low-latency needs (brief interactions).
* **Capability** — tool calling and native structured output require a provider
  that supports them. The router detects this from the provider profile and
  skips tiers that lack the required capability.
"""

from __future__ import annotations

from typing import Any

from applicant.adapters.llm.provider_profiles import get_profile
from applicant.ports.driven.llm import ChatMessage, TierLadder
from applicant.ports.driven.tier_router import (
    TierProfile,
    TierRoutingDecision,
)

# Rough chars-per-token heuristic (mirrors the LLM adapter's estimate).
_CHARS_PER_TOKEN = 4

# Thresholds that trigger capability-based escalation.
_TOOL_CALLING_TIER_COST_FLOOR = 1  # tiers with cost_score >= this support tools
_STRUCTURED_OUTPUT_TIER_COST_FLOOR = 1

# Complexity thresholds (in estimated tokens).
_COMPLEX_PROMPT_TOKENS = 500  # ~2000 chars → "complex" trigger
_LONG_CONTEXT_TOKENS = 2000  # ~8000 chars → prefer larger context windows


def _estimate_tokens(messages: list[ChatMessage]) -> int:
    chars = sum(len(m.role) + len(m.content) for m in messages)
    return max(1, chars // _CHARS_PER_TOKEN)


def _build_tier_profiles(ladder: TierLadder) -> list[TierProfile]:
    """Build capability metadata for every tier in the ladder.

    Detects provider type from the registered provider profiles and assigns
    cost/latency scores accordingly.
    """
    profiles: list[TierProfile] = []
    for _i, tier in enumerate(ladder.tiers):
        try:
            provider_profile = get_profile(tier.provider, tier.base_url)
            is_ollama = provider_profile.name == "ollama"
        except RuntimeError:
            is_ollama = False

        profiles.append(
            TierProfile(
                provider=tier.provider,
                model=tier.model,
                context_window=tier.context_window,
                cost_score=0.0 if is_ollama else 1.0,
                latency_score=0.3 if is_ollama else 1.0,
                supports_tools=False if is_ollama else provider_profile.supports_tools,
                supports_structured_output=not is_ollama,
            )
        )
    return profiles


def _find_cheapest_fitting(
    profiles: list[TierProfile],
    required_tokens: int,
    *,
    needs_tools: bool = False,
    needs_structured: bool = False,
) -> int | None:
    """Return the 0-based index of the cheapest tier that meets every requirement.

    Returns ``None`` if no tier fits.
    """
    best_idx: int | None = None
    best_cost: float | None = None

    for i, tp in enumerate(profiles):
        # Must fit the context window.
        if tp.context_window < required_tokens:
            continue
        # Must support tool calling if needed.
        if needs_tools and not tp.supports_tools:
            continue
        # Must support structured output if needed.
        if needs_structured and not tp.supports_structured_output:
            continue

        cost = tp.cost_score
        if best_idx is None or cost < best_cost:
            best_idx = i
            best_cost = cost
        elif cost == best_cost and tp.latency_score < profiles[best_idx].latency_score:
            # Tie-break by latency (faster is better).
            best_idx = i
            best_cost = cost

    return best_idx


def _needs_tools(tools: list[dict[str, Any]] | None) -> bool:
    """True iff the request includes tool schemas that require provider support."""
    return bool(tools)


def _needs_structured(json_schema: dict[str, Any] | None) -> bool:
    """True iff the request requires a JSON-schema structured response."""
    return json_schema is not None


def _estimate_complexity(messages: list[ChatMessage]) -> str:
    """Classify request complexity: ``simple``, ``moderate``, or ``complex``."""
    tok = _estimate_tokens(messages)
    if tok < _COMPLEX_PROMPT_TOKENS:
        return "simple"
    if tok < _LONG_CONTEXT_TOKENS:
        return "moderate"
    return "complex"


class SmartTierRouter:
    """Implements :class:`TierRouterPort` with cost/latency/capability heuristics.

    Construct with a ``TierLadder`` (the same ladder the :class:`LLMPort` uses).

    Usage::

        router = SmartTierRouter(ladder=my_ladder)
        decision = router.select_tier(messages, json_schema=my_schema)
        result = llm.complete(messages, start_tier=decision.start_tier)
    """

    def __init__(self, ladder: TierLadder) -> None:
        self._ladder = ladder
        self._profiles = _build_tier_profiles(ladder)

    # --- public API -------------------------------------------------------

    def select_tier(
        self,
        messages: list[ChatMessage],
        *,
        json_schema: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
        default_start: int = 1,
    ) -> TierRoutingDecision:
        """Recommend the optimal starting tier (1-based).

        The router:

        1. Estimates the token requirement of the messages.
        2. Checks whether tools or structured output are needed.
        3. Finds the cheapest tier that fits context + capability requirements.
        4. Falls back to ``default_start`` or the cheapest fitting tier.

        Returns a :class:`TierRoutingDecision` with a human-readable rationale.
        """
        required_tokens = _estimate_tokens(messages)
        needs_tools = _needs_tools(tools)
        needs_structured = _needs_structured(json_schema)
        complexity = _estimate_complexity(messages)

        parts: list[str] = []
        parts.append(f"~{required_tokens} tokens estimated")
        if needs_tools:
            parts.append("tool calling required")
        if needs_structured:
            parts.append("structured output required")

        # Find the cheapest tier that fits every requirement.
        idx = _find_cheapest_fitting(
            self._profiles,
            required_tokens,
            needs_tools=needs_tools,
            needs_structured=needs_structured,
        )

        if idx is None:
            # No tier fits: fall back to the default start. The LLMPort's own
            # ladder-climb logic will raise LLMLadderExhausted if nothing fits.
            # We note it in the rationale so operators can see the gap.
            return TierRoutingDecision(
                start_tier=default_start,
                rationale=f"no tier fits requirements ({', '.join(parts)}); "
                f"falling back to default start tier {default_start}",
            )

        # The cheapest fitting tier is the optimal start.
        recommended = idx + 1  # convert to 1-based
        tp = self._profiles[idx]
        parts.append(f"provider={tp.provider}")
        parts.append(f"model={tp.model}")
        parts.append(f"cost={tp.cost_score}")
        parts.append(f"complexity={complexity}")

        return TierRoutingDecision(
            start_tier=recommended,
            rationale=f"optimal start tier {recommended}: {', '.join(parts)}",
        )

    def describe_tiers(self) -> list[TierProfile]:
        """Return capability metadata for every configured tier."""
        return list(self._profiles)

    # --- helpers (exposed for testing) ------------------------------------

    @property
    def ladder(self) -> TierLadder:
        return self._ladder

    @property
    def profiles(self) -> list[TierProfile]:
        return list(self._profiles)
