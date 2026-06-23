"""Regression tests for `_sanitize_llm_messages` — blank turns must never be
sent to a provider.

A blank/whitespace-only message used to be forwarded verbatim (it had a
`content` key, so it passed the old filter). Providers like DeepSeek and
Anthropic reject a turn whose content is empty, and such blanks creep into a
session's history from several paths (attachment-only sends, a model that
returns nothing, webhook/scheduled-task writes) and then replay on every
later call. They must be dropped — unless the turn carries a tool call or a
tool result, whose payload is its content.
"""
from src import llm_core


def _roles(messages):
    return [m["role"] for m in messages]


def test_drops_empty_string_content():
    msgs = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": ""},
        {"role": "user", "content": "are you there?"},
    ]
    out = llm_core._sanitize_llm_messages(msgs)
    assert _roles(out) == ["user", "user"]
    assert all(m["content"].strip() for m in out)


def test_drops_whitespace_only_content():
    msgs = [{"role": "user", "content": "   \n\t  "}]
    assert llm_core._sanitize_llm_messages(msgs) == []


def test_keeps_normal_messages_unchanged():
    msgs = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "hi"},
    ]
    out = llm_core._sanitize_llm_messages(msgs)
    assert out == msgs


def test_strips_applicant_only_metadata():
    msgs = [{"role": "user", "content": "hi", "metadata": {"x": 1}, "thinking": True}]
    out = llm_core._sanitize_llm_messages(msgs)
    assert out == [{"role": "user", "content": "hi"}]


def test_keeps_assistant_tool_calls_with_blank_text():
    """A tool-call turn legitimately has empty text — its payload is content."""
    msgs = [{
        "role": "assistant",
        "content": "",
        "tool_calls": [{"id": "c1", "function": {"name": "bash", "arguments": "{}"}}],
    }]
    out = llm_core._sanitize_llm_messages(msgs)
    assert len(out) == 1
    assert out[0]["tool_calls"]


def test_keeps_tool_result_with_blank_text():
    msgs = [{"role": "tool", "content": "", "tool_call_id": "c1"}]
    out = llm_core._sanitize_llm_messages(msgs)
    assert len(out) == 1


def test_keeps_multimodal_image_only_turn():
    """Vision turn with no text but an image block is not blank."""
    msgs = [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA"}},
    ]}]
    out = llm_core._sanitize_llm_messages(msgs)
    assert len(out) == 1


def test_drops_multimodal_all_blank_text():
    msgs = [{"role": "user", "content": [{"type": "text", "text": "  "}]}]
    assert llm_core._sanitize_llm_messages(msgs) == []


def test_keeps_multimodal_with_text():
    msgs = [{"role": "user", "content": [{"type": "text", "text": "describe"}]}]
    out = llm_core._sanitize_llm_messages(msgs)
    assert len(out) == 1


def test_skips_non_dict_and_roleless_entries():
    msgs = [
        "not a dict",
        {"content": "orphan, no role"},
        {"role": "user", "content": "kept"},
    ]
    out = llm_core._sanitize_llm_messages(msgs)
    assert out == [{"role": "user", "content": "kept"}]


def test_empty_and_none_input():
    assert llm_core._sanitize_llm_messages([]) == []
    assert llm_core._sanitize_llm_messages(None) == []
