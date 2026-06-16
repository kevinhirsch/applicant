"""Hermetic tests for the OpenAI-compatible LLM adapter (FR-LLM-1..5).

All HTTP is faked via ``httpx.MockTransport`` — no live network. Covers: model
auto-pull (both provider styles), ladder climb on context overflow + low
confidence, structured-output native + prompt fallback, and ceiling exhaustion.
"""

from __future__ import annotations

import json

import httpx
import pytest

from applicant.adapters.llm.openai_compatible import OpenAICompatibleLLM
from applicant.ports.driven.llm import (
    ChatMessage,
    LLMLadderExhausted,
    TierConfig,
    TierLadder,
)


def _openai_models_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={"data": [{"id": "gpt-4o-mini"}, {"id": "gpt-4o"}]},
    )


def _ollama_tags_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={"models": [{"name": "llama3.1:8b"}, {"name": "qwen2.5:14b"}]},
    )


# --- FR-LLM-2: model auto-pull --------------------------------------------
def test_list_models_openai_style():
    transport = httpx.MockTransport(_openai_models_handler)
    llm = OpenAICompatibleLLM(
        provider="openrouter",
        base_url="https://openrouter.ai/api/v1",
        api_key="sk-x",
        model="gpt-4o-mini",
        transport=transport,
    )
    assert llm.list_models() == ["gpt-4o-mini", "gpt-4o"]


def test_list_models_ollama_style():
    transport = httpx.MockTransport(_ollama_tags_handler)
    llm = OpenAICompatibleLLM(
        provider="ollama",
        base_url="http://localhost:11434",
        model="llama3.1:8b",
        transport=transport,
    )
    assert llm.list_models() == ["llama3.1:8b", "qwen2.5:14b"]


def test_list_models_no_auth_header_for_ollama():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json={"models": []})

    llm = OpenAICompatibleLLM(
        provider="ollama",
        base_url="http://localhost:11434",
        model="llama3.1",
        api_key="should-not-be-sent",
        transport=httpx.MockTransport(handler),
    )
    llm.list_models()
    assert seen["auth"] is None


# --- FR-LLM-1: basic completion -------------------------------------------
def _chat_text_handler(text: str):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": text}}]},
        )

    return handler


def test_complete_basic_openai():
    transport = httpx.MockTransport(_chat_text_handler("hello world"))
    llm = OpenAICompatibleLLM(
        provider="openai",
        base_url="https://api.openai.com/v1",
        api_key="sk-x",
        model="gpt-4o-mini",
        transport=transport,
    )
    res = llm.complete([ChatMessage(role="user", content="hi")])
    assert res.text == "hello world"
    assert res.tier == 1
    assert res.model == "gpt-4o-mini"


def test_complete_basic_ollama():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/chat"
        return httpx.Response(200, json={"message": {"content": "local reply"}})

    llm = OpenAICompatibleLLM(
        provider="ollama",
        base_url="http://localhost:11434/v1",
        model="llama3.1",
        transport=httpx.MockTransport(handler),
    )
    res = llm.complete([ChatMessage(role="user", content="hi")])
    assert res.text == "local reply"


# --- FR-LLM-4: ladder climb -----------------------------------------------
def test_climb_on_context_overflow_picks_fitting_tier():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body["model"])
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": f"from {body['model']}"}}]},
        )

    transport = httpx.MockTransport(handler)
    ladder = TierLadder(
        tiers=[
            TierConfig(provider="openai", base_url="https://a/v1", model="small", context_window=10),
            TierConfig(provider="openai", base_url="https://a/v1", model="mid", context_window=50),
            TierConfig(provider="openai", base_url="https://a/v1", model="big", context_window=100_000),
        ]
    )
    llm = OpenAICompatibleLLM(ladder=ladder, transport=transport)
    # A long prompt overflows tier 1 (10) and tier 2 (50); jumps to tier 3.
    big_prompt = "x" * 4000  # ~1000 tokens estimated
    res = llm.complete([ChatMessage(role="user", content=big_prompt)])
    assert res.model == "big"
    assert res.tier == 3
    # Only the fitting tier was actually called (no wasted requests).
    assert calls == ["big"]


def test_climb_on_low_confidence():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["model"] == "small":
            text = "I'm not sure about this."
        else:
            text = "Definitive answer."
        return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})

    ladder = TierLadder(
        tiers=[
            TierConfig(provider="openai", base_url="https://a/v1", model="small", context_window=100_000),
            TierConfig(provider="openai", base_url="https://a/v1", model="big", context_window=100_000),
        ]
    )
    llm = OpenAICompatibleLLM(ladder=ladder, transport=httpx.MockTransport(handler))
    res = llm.complete([ChatMessage(role="user", content="hard q")])
    assert res.tier == 2
    assert res.text == "Definitive answer."


def test_start_tier_respected():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": body["model"]}}]})

    ladder = TierLadder(
        tiers=[
            TierConfig(provider="openai", base_url="https://a/v1", model="t1", context_window=100_000),
            TierConfig(provider="openai", base_url="https://a/v1", model="t2", context_window=100_000),
        ]
    )
    llm = OpenAICompatibleLLM(ladder=ladder, transport=httpx.MockTransport(handler))
    res = llm.complete([ChatMessage(role="user", content="q")], start_tier=2)
    assert res.tier == 2 and res.text == "t2"


# --- FR-LLM-4: ceiling exhaustion -----------------------------------------
def test_ceiling_exhaustion_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    ladder = TierLadder(
        tiers=[
            TierConfig(provider="openai", base_url="https://a/v1", model="t1", context_window=100_000),
            TierConfig(provider="openai", base_url="https://a/v1", model="t2", context_window=100_000),
        ]
    )
    llm = OpenAICompatibleLLM(ladder=ladder, transport=httpx.MockTransport(handler))
    with pytest.raises(LLMLadderExhausted):
        llm.complete([ChatMessage(role="user", content="q")])


def test_no_fitting_tier_raises():
    ladder = TierLadder(
        tiers=[TierConfig(provider="openai", base_url="https://a/v1", model="t1", context_window=5)]
    )
    llm = OpenAICompatibleLLM(ladder=ladder, transport=httpx.MockTransport(_chat_text_handler("x")))
    with pytest.raises(LLMLadderExhausted):
        llm.complete([ChatMessage(role="user", content="x" * 4000)])


# --- FR-LLM-4a: structured output -----------------------------------------
_SCHEMA = {"type": "object", "required": ["score"], "properties": {"score": {"type": "integer"}}}


def test_structured_output_native_json():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body.get("response_format", {}).get("type") == "json_schema"
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"score": 7}'}}]}
        )

    llm = OpenAICompatibleLLM(
        provider="openai", base_url="https://a/v1", model="m",
        transport=httpx.MockTransport(handler),
    )
    res = llm.complete([ChatMessage(role="user", content="rate")], json_schema=_SCHEMA)
    assert res.structured == {"score": 7}


def test_structured_output_prompt_fallback():
    state = {"calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        state["calls"] += 1
        if state["calls"] == 1:
            # Native attempt returns junk (no valid JSON).
            return httpx.Response(
                200, json={"choices": [{"message": {"content": "sorry, no idea"}}]}
            )
        # Fallback: schema injected into the prompt as a system message.
        assert any("JSON schema" in m["content"] for m in body["messages"])
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "```json\n{\"score\": 3}\n```"}}]}
        )

    llm = OpenAICompatibleLLM(
        provider="openai", base_url="https://a/v1", model="m",
        transport=httpx.MockTransport(handler),
    )
    res = llm.complete([ChatMessage(role="user", content="rate")], json_schema=_SCHEMA)
    assert res.structured == {"score": 3}
    assert state["calls"] == 2


def test_ollama_structured_output():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body.get("format") == "json"
        return httpx.Response(200, json={"message": {"content": '{"score": 9}'}})

    llm = OpenAICompatibleLLM(
        provider="ollama", base_url="http://localhost:11434", model="llama3.1",
        transport=httpx.MockTransport(handler),
    )
    res = llm.complete([ChatMessage(role="user", content="rate")], json_schema=_SCHEMA)
    assert res.structured == {"score": 9}


# --- FR-UI-5: gate --------------------------------------------------------
def test_is_configured():
    assert OpenAICompatibleLLM().is_configured() is False
    assert (
        OpenAICompatibleLLM(provider="ollama", model="llama3.1").is_configured() is True
    )


def test_provider_context_error_climbs():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["model"] == "small":
            return httpx.Response(400, json={"error": {"message": "maximum context length exceeded"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    ladder = TierLadder(
        tiers=[
            TierConfig(provider="openai", base_url="https://a/v1", model="small", context_window=100_000),
            TierConfig(provider="openai", base_url="https://a/v1", model="big", context_window=100_000),
        ]
    )
    llm = OpenAICompatibleLLM(ladder=ladder, transport=httpx.MockTransport(handler))
    res = llm.complete([ChatMessage(role="user", content="q")])
    assert res.tier == 2 and res.text == "ok"
