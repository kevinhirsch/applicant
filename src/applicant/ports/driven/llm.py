"""LLM port (FR-LLM-1..5).

Provider-agnostic: an OpenAI-compatible cloud API and/or local/network Ollama;
the system can run fully local. The adapter auto-populates the model list
(FR-LLM-2), honors a capability-ranked tier ladder (FR-LLM-3/4), and is robust to
model variance in function-calling / JSON-mode (FR-LLM-4a). LLM is the last resort
for token frugality (FR-LLM-5, NFR-TOKEN-1).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class ChatMessage:
    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass(frozen=True)
class LLMResult:
    text: str
    tier: int  # which ladder tier produced this (1-based)
    model: str
    raw: dict[str, Any] | None = None


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

        When ``json_schema`` is given the adapter must defensively parse and fall
        back to prompt-based structured output (FR-LLM-4a). The top tier is the
        ceiling; on exhaustion surface gracefully (FR-LLM-4).
        """
        ...

    def is_configured(self) -> bool:
        """True once a provider/model/endpoint is set (gates downstream, FR-UI-5)."""
        ...
