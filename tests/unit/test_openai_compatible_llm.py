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


def test_list_models_ollama_strips_v1_suffix():
    # FR-LLM-2: an Ollama base ending in /v1 must still hit /api/tags (not /v1/api/tags).
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        return httpx.Response(200, json={"models": [{"name": "llama3.1:8b"}]})

    llm = OpenAICompatibleLLM(
        provider="ollama",
        base_url="http://gpu:11434/v1",
        model="llama3.1:8b",
        transport=httpx.MockTransport(handler),
    )
    assert llm.list_models() == ["llama3.1:8b"]
    assert seen["path"] == "/api/tags"


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


def test_complete_openrouter_hits_chat_completions_not_ollama():
    # Regression: OpenRouter's base "https://openrouter.ai/api/v1" contains "/api/",
    # which used to misclassify it as Ollama and POST to /api/api/chat (404), silently
    # falling back to the deterministic stub. An explicit non-ollama provider must
    # take the OpenAI path: <base>/chat/completions.
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["path"] = request.url.path
        return httpx.Response(
            200, json={"choices": [{"message": {"role": "assistant", "content": "real reply"}}]}
        )

    llm = OpenAICompatibleLLM(
        provider="openrouter",
        base_url="https://openrouter.ai/api/v1",
        api_key="sk-x",
        model="z-ai/glm-5.2",
        transport=httpx.MockTransport(handler),
    )
    res = llm.complete([ChatMessage(role="user", content="hi")])
    assert res.text == "real reply"
    assert seen["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert "/api/api/chat" not in seen["url"]


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


def test_start_tier_beyond_ladder_clamps_to_top():
    # A heavy task may request start_tier=2 (escalate immediately); on a single-tier
    # ladder that must clamp to the top tier, not index past the end (FR-LLM-3/4).
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": body["model"]}}]})

    ladder = TierLadder(
        tiers=[
            TierConfig(provider="openai", base_url="https://a/v1", model="only", context_window=100_000),
        ]
    )
    llm = OpenAICompatibleLLM(ladder=ladder, transport=httpx.MockTransport(handler))
    res = llm.complete([ChatMessage(role="user", content="q")], start_tier=2)
    assert res.tier == 1 and res.text == "only"


def test_start_tier_falls_back_down_when_upper_tier_auth_fails():
    """Regression: heavy writing starts at tier 2; if the configured upper tier(s)
    return a hard auth error (401), the ladder must fall back DOWN to a healthy
    LOWER configured tier — not exhaust into the canned deterministic fallback."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["model"] == "t2":
            # Misconfigured upper tier: hard auth failure.
            return httpx.Response(401, json={"error": "invalid api key"})
        return httpx.Response(200, json={"choices": [{"message": {"content": body["model"]}}]})

    ladder = TierLadder(
        tiers=[
            TierConfig(provider="openai", base_url="https://a/v1", model="t1", context_window=100_000),
            TierConfig(provider="openai", base_url="https://a/v1", model="t2", context_window=100_000),
        ]
    )
    llm = OpenAICompatibleLLM(ladder=ladder, transport=httpx.MockTransport(handler))
    res = llm.complete([ChatMessage(role="user", content="q")], start_tier=2)
    # The healthy lower tier's output is used, not an exhaustion.
    assert res.tier == 1 and res.text == "t1"


def test_start_tier_total_failure_still_exhausts():
    """When the upper tier fails AND the lower tier also fails, the ladder is fully
    exhausted (so the caller can mark the draft degraded) — it does not hang."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "invalid api key"})

    ladder = TierLadder(
        tiers=[
            TierConfig(provider="openai", base_url="https://a/v1", model="t1", context_window=100_000),
            TierConfig(provider="openai", base_url="https://a/v1", model="t2", context_window=100_000),
        ]
    )
    llm = OpenAICompatibleLLM(ladder=ladder, transport=httpx.MockTransport(handler))
    with pytest.raises(LLMLadderExhausted):
        llm.complete([ChatMessage(role="user", content="q")], start_tier=2)


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


def test_structured_output_fallback_revalidates_schema():
    # FR-LLM-4a: when the prompt fallback returns parseable JSON that is missing a
    # required key, it must NOT be returned as structured (re-validate the fallback).
    state = {"calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        if state["calls"] == 1:
            # Native attempt: invalid (missing required "score").
            return httpx.Response(
                200, json={"choices": [{"message": {"content": '{"wrong": 1}'}}]}
            )
        # Fallback: parseable JSON but STILL missing the required "score" key.
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"other": 2}'}}]}
        )

    llm = OpenAICompatibleLLM(
        provider="openai", base_url="https://a/v1", model="m",
        transport=httpx.MockTransport(handler),
    )
    res = llm.complete([ChatMessage(role="user", content="rate")], json_schema=_SCHEMA)
    assert res.structured is None
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


# --- #285: _is_context_error false-positive regression -------------------
def test_is_context_error_real_overflow_detected():
    """A genuine context_length_exceeded error must be detected."""
    resp = httpx.Response(
        400,
        json={"error": {"code": "context_length_exceeded", "message": "maximum context length"}},
    )
    assert OpenAICompatibleLLM._is_context_error(resp) is True


def test_is_context_error_content_filter_not_detected():
    """A content-filter rejection that mentions 'context' must NOT trip the overflow handler."""
    resp = httpx.Response(
        400,
        json={
            "error": {
                "code": "content_filter",
                "message": "Your request was rejected in the context of the request policy.",
            }
        },
    )
    assert OpenAICompatibleLLM._is_context_error(resp) is False


def test_is_context_error_normal_response_not_detected():
    """A successful response whose text mentions 'context' must not trip the overflow handler."""
    resp = httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {
                        "content": "Here is the relevant context for your question."
                    }
                }
            ]
        },
    )
    assert OpenAICompatibleLLM._is_context_error(resp) is False


def test_is_context_error_too_many_tokens_detected():
    """An 'too many tokens' phrase in the error body must be detected as overflow."""
    resp = httpx.Response(
        413,
        json={"error": {"message": "Request failed: too many tokens in the input."}},
    )
    assert OpenAICompatibleLLM._is_context_error(resp) is True


def test_content_filter_does_not_escalate_tier():
    """A content-filter rejection must NOT trigger a tier climb (#285 regression).

    Before the fix, a 400 with "context" anywhere in the body climbed the ladder
    instead of raising HTTPStatusError. After the fix it must surface as an error
    (the ladder exhausts at one tier), not silently succeed on tier 2.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "error": {
                    "code": "content_filter",
                    "message": "Request blocked in the context of content policy.",
                }
            },
        )

    ladder = TierLadder(
        tiers=[
            TierConfig(
                provider="openai",
                base_url="https://a/v1",
                model="small",
                context_window=100_000,
            ),
        ]
    )
    llm = OpenAICompatibleLLM(ladder=ladder, transport=httpx.MockTransport(handler))
    with pytest.raises((LLMLadderExhausted, httpx.HTTPStatusError)):
        llm.complete([ChatMessage(role="user", content="q")])


# --- FR-LLM-4a: robust JSON extraction ------------------------------------
import pytest as _pytest  # noqa: E402

from applicant.adapters.llm.openai_compatible import _extract_json  # noqa: E402


@_pytest.mark.parametrize(
    "text,expected",
    [
        # prose-prefixed JSON
        ('Sure! Here is the result:\n{"name": "Ada", "ok": true}', {"name": "Ada", "ok": True}),
        # a decoy {...} before the real (parseable) object
        ("note {not json here} then {\"name\": \"Ada\"}", {"name": "Ada"}),
        # trailing comma tolerated
        ('{"a": 1, "b": 2,}', {"a": 1, "b": 2}),
        # brace inside a string value must not end the object early
        ('{"expr": "f(x) = { y }", "n": 3}', {"expr": "f(x) = { y }", "n": 3}),
        # fenced
        ('```json\n{"x": 9}\n```', {"x": 9}),
    ],
)
def test_extract_json_robust(text, expected):
    assert _extract_json(text) == expected


def test_extract_json_decoy_before_real_picks_real():
    # First balanced span is unparseable; the second parses -> returned.
    txt = 'prefix {oops} suffix {"answer": 42, "tags": ["a","b",]}'
    assert _extract_json(txt) == {"answer": 42, "tags": ["a", "b"]}


def test_complete_parses_native_tool_calls():
    schema = {"required": ["company", "role"]}

    def handler(request: httpx.Request) -> httpx.Response:
        # content is null; structured payload is in tool_calls[].function.arguments
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "extract",
                                        "arguments": '{"company": "Acme", "role": "SWE"}',
                                    },
                                }
                            ],
                        }
                    }
                ]
            },
        )

    ladder = TierLadder(
        tiers=[TierConfig(provider="openai", base_url="https://a/v1", model="m", context_window=100_000)]
    )
    llm = OpenAICompatibleLLM(ladder=ladder, transport=httpx.MockTransport(handler))
    res = llm.complete([ChatMessage(role="user", content="q")], json_schema=schema)
    assert res.structured == {"company": "Acme", "role": "SWE"}


# --- FR-MIND-6: tool / function calling seam ------------------------------
def test_supports_tools_openai_yes_ollama_no():
    openai_llm = OpenAICompatibleLLM(
        provider="openai", base_url="https://a/v1", model="gpt-4o-mini",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})),
    )
    ollama_llm = OpenAICompatibleLLM(
        provider="ollama", base_url="http://localhost:11434", model="llama3.1:8b",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})),
    )
    assert openai_llm.supports_tools() is True
    assert ollama_llm.supports_tools() is False


def test_complete_with_tools_parses_tool_calls():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json={
            "choices": [{
                "message": {
                    "content": None,
                    "tool_calls": [{
                        "id": "call_42",
                        "type": "function",
                        "function": {"name": "recall", "arguments": "{\"query\": \"x\"}"},
                    }],
                }
            }]
        })

    llm = OpenAICompatibleLLM(
        provider="openai", base_url="https://a/v1", model="gpt-4o-mini",
        transport=httpx.MockTransport(handler),
    )
    tools = [{"type": "function", "function": {"name": "recall", "parameters": {}}}]
    res = llm.complete_with_tools([ChatMessage(role="user", content="q")], tools)
    # The request carried the tools + tool_choice.
    assert captured["payload"]["tools"] == tools
    assert captured["payload"]["tool_choice"] == "auto"
    # The response's tool call was parsed.
    assert len(res.tool_calls) == 1
    assert res.tool_calls[0].id == "call_42"
    assert res.tool_calls[0].name == "recall"
    assert res.text == ""


def test_complete_with_tools_plain_text_when_no_calls():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "final answer"}}]
        })

    llm = OpenAICompatibleLLM(
        provider="openai", base_url="https://a/v1", model="gpt-4o-mini",
        transport=httpx.MockTransport(handler),
    )
    res = llm.complete_with_tools([ChatMessage(role="user", content="q")], [])
    assert res.tool_calls == ()
    assert res.text == "final answer"


def test_tool_result_messages_serialize_to_wire_shape():
    from applicant.ports.driven.llm import ToolCall

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    llm = OpenAICompatibleLLM(
        provider="openai", base_url="https://a/v1", model="gpt-4o-mini",
        transport=httpx.MockTransport(handler),
    )
    messages = [
        ChatMessage(role="user", content="do it"),
        ChatMessage(role="assistant", content="",
                    tool_calls=(ToolCall(id="c1", name="recall", arguments="{}"),)),
        ChatMessage(role="tool", content="found nothing", tool_call_id="c1"),
    ]
    llm.complete_with_tools(messages, [])
    wire = captured["payload"]["messages"]
    # The assistant message round-trips its tool_calls; the tool result carries its id.
    assert wire[1]["tool_calls"][0]["function"]["name"] == "recall"
    assert wire[2]["role"] == "tool" and wire[2]["tool_call_id"] == "c1"
