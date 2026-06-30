"""Tier router port (FR-LLM-3/4 extension).

Smart routing between local and cloud models based on cost, latency, and
capability requirements. Decides which ladder tier to start at for a given
request, avoiding unnecessary cloud spend for simple tasks and avoiding
local-model capability gaps for complex ones.

The port is OPTIONAL — callers that don't wire a tier router default to the
existing ``start_tier=1`` behaviour (cheapest tier first, climb on failure).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from applicant.ports.driven.llm import ChatMessage


@dataclass(frozen=True)
class TierRoutingDecision:
    """The router's recommendation for one completion request.

    ``start_tier`` is the 1-based tier index to begin at (passed to
    :meth:`LLMPort.complete` as ``start_tier``). ``rationale`` explains
    why this tier was selected, aiding observability.
    """

    start_tier: int = 1
    rationale: str = ""


@dataclass(frozen=True)
class TierProfile:
    """Cost/latency/capability metadata for one ladder tier.

    Used by the router to compare tiers without making real API calls.
    """

    provider: str
    model: str
    context_window: int
    # Relative cost (0 = free, 1 = baseline, >1 = progressively more expensive).
    # Auto-detected: ``ollama`` tiers cost 0; cloud tiers cost 1+.
    cost_score: float = 0.0
    # Relative latency estimate (0 = instant, 1 = baseline cloud, >1 = slower).
    # Local models usually have lower latency for simple prompts; very large
    # local models may be slower than a fast cloud endpoint.
    latency_score: float = 1.0
    # True iff the provider supports tool/function calling.
    supports_tools: bool = False
    # True iff the provider supports native JSON-structured output (response_format).
    supports_structured_output: bool = False


@runtime_checkable
class TierRouterPort(Protocol):
    """Outbound port for smart tier selection.

    A router inspects the request and the available tier ladder to recommend the
    optimal starting tier, balancing cost, latency, and capability requirements.
    """

    def select_tier(
        self,
        messages: list[ChatMessage],
        *,
        json_schema: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
        default_start: int = 1,
    ) -> TierRoutingDecision:
        """Recommend the optimal starting tier for a completion request.

        ``messages`` — the full message list (used to estimate complexity and
        context requirement). ``json_schema`` and ``tools`` indicate whether
        structured output or tool calling is needed. ``default_start`` is the
        caller's default start tier (usually 1).

        Returns a :class:`TierRoutingDecision` with the recommended start tier
        and a human-readable rationale for the choice.
        """
        ...

    def describe_tiers(self) -> list[TierProfile]:
        """Return capability/cost metadata for every configured tier.

        Used for observability and debugging — e.g. the setup wizard can display
        which models are local vs cloud and what each supports.
        """
        ...
