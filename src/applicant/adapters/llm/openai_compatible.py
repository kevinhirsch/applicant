"""OpenAI-compatible LLM adapter (FR-LLM-1..5).

# STAGE B — owned by Phase 0 / Phase 1; flesh out here.

Talks to any OpenAI-compatible endpoint (OpenRouter cloud or local/network Ollama).
Phase 0 implements: model auto-pull (FR-LLM-2), the tier ladder + escalation
(FR-LLM-3/4), and defensive structured-output parsing (FR-LLM-4a). For now it
returns minimal placeholders and reports configured/unconfigured for the OOBE gate.
"""

from __future__ import annotations

from applicant.ports.driven.llm import ChatMessage, LLMResult


class OpenAICompatibleLLM:
    """LLMPort adapter (stub). Configuration drives the OOBE gate (FR-UI-5)."""

    def __init__(self, *, provider: str = "", base_url: str = "", api_key: str = "", model: str = "") -> None:
        self._provider = provider
        self._base_url = base_url
        self._api_key = api_key
        self._model = model

    def list_models(self) -> list[str]:
        # STAGE B: auto-populate from the provider's /models endpoint (FR-LLM-2).
        return [self._model] if self._model else []

    def complete(
        self,
        messages: list[ChatMessage],
        *,
        start_tier: int = 1,
        json_schema=None,
        max_tokens=None,
    ) -> LLMResult:
        # STAGE B: real HTTP call + tier-ladder escalation + defensive parse.
        raise NotImplementedError("STAGE B — Phase 0/1: implement OpenAI-compatible completion.")

    def is_configured(self) -> bool:
        return bool(self._provider and self._model)
