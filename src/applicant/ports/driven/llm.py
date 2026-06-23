"""LLM port (FR-LLM-1..5).

Provider-agnostic: an OpenAI-compatible cloud API and/or local/network Ollama;
the system can run fully local. The adapter auto-populates the model list
(FR-LLM-2), honors a capability-ranked tier ladder (FR-LLM-3/4), and is robust to
model variance in function-calling / JSON-mode (FR-LLM-4a). LLM is the last resort
for token frugality (FR-LLM-5, NFR-TOKEN-1).

A *tier* is one rung on the escalation ladder: a concrete {provider, base_url,
api_key, model, context_window}. ``complete`` starts at the lowest sufficient tier
and CLIMBS on low-confidence signals or context overflow; the top tier is the
ceiling — on exhaustion the adapter raises :class:`LLMLadderExhausted` rather than
failing silently (FR-LLM-4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


class LLMError(Exception):
    """Base class for typed LLM domain errors."""


class LLMLadderExhausted(LLMError):
    """Raised when every tier on the ladder has been tried and none succeeded.

    Carries the last underlying error so callers can surface it gracefully.
    """

    def __init__(self, message: str, *, last_error: Exception | None = None) -> None:
        super().__init__(message)
        self.last_error = last_error


class LLMNotConfigured(LLMError):
    """Raised when a completion is attempted before any tier is configured."""


@dataclass(frozen=True)
class TierConfig:
    """One rung on the capability-ranked tier ladder (FR-LLM-3).

    ``provider`` is one of ``"openrouter"``, ``"openai"`` (OpenAI-compatible cloud)
    or ``"ollama"`` (local/network). ``context_window`` is the model's token budget
    and drives overflow-based escalation (FR-LLM-4/4a).
    """

    provider: str
    base_url: str
    model: str
    api_key: str = ""
    context_window: int = 8192


@dataclass(frozen=True)
class TierLadder:
    """Ordered ladder of tiers, L1 (cheapest/local default) -> LN (ceiling).

    1-N tiers, default 3 in the wizard; reorderable (FR-LLM-3).
    """

    tiers: list[TierConfig] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.tiers:
            raise ValueError("A tier ladder needs at least one tier.")

    def __len__(self) -> int:
        return len(self.tiers)

    def at(self, index: int) -> TierConfig:
        return self.tiers[index]

    def first_fitting(self, required_context: int, *, from_index: int = 0) -> int | None:
        """Index of the first tier at/after ``from_index`` whose window fits.

        Picks the next tier that can actually hold ``required_context`` — not
        blindly +1 (FR-LLM-4).
        """
        for i in range(max(0, from_index), len(self.tiers)):
            if self.tiers[i].context_window >= required_context:
                return i
        return None


@dataclass(frozen=True)
class ChatMessage:
    role: str  # "system" | "user" | "assistant" | "tool"
    content: str
    # FR-MIND-6: optional tool-call round-trip fields. They default to empty, so a
    # plain (role, content) message is byte-identical to before and every existing
    # call site keeps working unchanged. ``tool_calls`` carries the assistant's
    # requested calls (echoed back so the provider can thread the conversation);
    # ``tool_call_id`` tags a ``role="tool"`` result message back to its call.
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None


@dataclass(frozen=True)
class ToolCall:
    """One tool/function call the model requested (FR-MIND-6).

    ``arguments`` is the raw JSON-string the model emitted (parsed by the dispatcher,
    defensively, exactly like structured output — FR-LLM-4a). ``id`` ties a tool
    result message back to the call that produced it.
    """

    id: str
    name: str
    arguments: str = "{}"


@dataclass(frozen=True)
class ToolCallResult:
    """The outcome of one tool-capable completion turn (FR-MIND-6).

    Either the model requested ``tool_calls`` (and ``text`` is usually empty), or it
    returned a final ``text`` reply with no calls. The caller dispatches the calls,
    feeds the results back, and loops until the model stops calling tools or the round
    cap is hit.
    """

    text: str
    tool_calls: tuple[ToolCall, ...] = ()
    tier: int = 1
    model: str = ""
    raw: dict[str, Any] | None = None


@dataclass(frozen=True)
class LLMResult:
    text: str
    tier: int  # which ladder tier produced this (1-based)
    model: str
    raw: dict[str, Any] | None = None
    structured: dict[str, Any] | None = None  # parsed JSON when json_schema given
    low_confidence: bool = False


@runtime_checkable
class LLMPort(Protocol):
    """Outbound port for LLM reasoning/generation."""

    def list_models(self) -> list[str]:
        """Return models available from the configured provider (FR-LLM-2)."""
        ...

    def complete(
        self,
        messages: list[ChatMessage],
        *,
        start_tier: int = 1,
        json_schema: dict[str, Any] | None = None,
        max_tokens: int | None = None,
    ) -> LLMResult:
        """Run a completion, climbing the tier ladder on low confidence / overflow.

        ``start_tier`` is the 1-based starting rung (per-task starting tier,
        FR-LLM-4). When ``json_schema`` is given the adapter must defensively parse
        and fall back to prompt-based structured output (FR-LLM-4a). The top tier is
        the ceiling; on exhaustion raise :class:`LLMLadderExhausted` (FR-LLM-4).
        """
        ...

    def is_configured(self) -> bool:
        """True once a provider/model/endpoint is set (gates downstream, FR-UI-5)."""
        ...

    # --- FR-MIND-6: optional tool/function calling ------------------------
    # These two are CAPABILITY-GATED extensions. A caller checks ``supports_tools()``
    # first; when it is False (a local Ollama lane, or an unconfigured ladder) the
    # caller falls back to the single-shot ``complete`` path — so default behavior is
    # unchanged. The base Protocol gives both a defaulted body so an adapter that does
    # NOT implement them is still a valid ``LLMPort`` (back-compat).

    def supports_tools(self) -> bool:
        """True iff the configured provider advertises OpenAI-style tool calling.

        Detected from the provider profile (FR-MIND-6). False keeps the chat on its
        current single-shot path, byte-identical to today.
        """
        return False

    def complete_with_tools(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]],
        *,
        start_tier: int = 1,
        max_tokens: int | None = None,
    ) -> ToolCallResult:
        """One tool-capable completion turn (FR-MIND-6).

        Sends ``tools`` (OpenAI function schemas) to the model and returns either the
        tool calls it requested or its final text. The caller runs the dispatch loop.
        Raises :class:`LLMLadderExhausted` on exhaustion, like :meth:`complete`.
        """
        ...
