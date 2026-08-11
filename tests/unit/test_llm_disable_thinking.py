"""Unit tests for LLM_DISABLE_THINKING opt-in toggle (FR-LLM-THINK)."""

from __future__ import annotations

import pytest

from applicant.adapters.llm.openai_compatible import OpenAICompatibleLLM


class TestDisableThinkingToggle:
    """Verify _apply_thinking_toggle behaviour under different env settings."""

    def test_off_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LLM_DISABLE_THINKING", raising=False)
        llm = OpenAICompatibleLLM()
        result = llm._apply_thinking_toggle({})
        assert "chat_template_kwargs" not in result

    def test_on_adds_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_DISABLE_THINKING", "true")
        llm = OpenAICompatibleLLM()
        result = llm._apply_thinking_toggle({})
        assert result["chat_template_kwargs"]["enable_thinking"] is False

    def test_preserves_existing_kwargs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_DISABLE_THINKING", "1")
        llm = OpenAICompatibleLLM()
        payload = {"chat_template_kwargs": {"foo": 1}}
        result = llm._apply_thinking_toggle(payload)
        assert result["chat_template_kwargs"]["foo"] == 1
        assert result["chat_template_kwargs"]["enable_thinking"] is False
