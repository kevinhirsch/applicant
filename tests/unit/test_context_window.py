"""Unit tests for engine context management (FR-MIND-8, FR-MIND-13).

Cover the pure ``ContextWindowManager`` (keep system + recent, compress middle,
image-aware estimate, no-op when disabled) and the adapter-level prefix-cache
gating (breakpoints only for a capability-advertising provider, never otherwise).
"""

from __future__ import annotations

import httpx

from applicant.adapters.llm.context_window import (
    _TOKENS_PER_IMAGE,
    ContextWindowManager,
    estimate_tokens,
)
from applicant.adapters.llm.openai_compatible import OpenAICompatibleLLM
from applicant.adapters.llm.provider_profiles import (
    OPENAI_PROFILE,
    ProviderProfile,
)
from applicant.ports.driven.llm import ChatMessage, TierConfig, TierLadder

# --- ContextWindowManager (pure) -------------------------------------------

def _convo(n_middle: int) -> list[ChatMessage]:
    """system + n middle turns + a few recent turns, each large enough to count."""
    msgs = [ChatMessage(role="system", content="SYSTEM " * 50)]
    for i in range(n_middle):
        msgs.append(ChatMessage(role="user", content=f"middle-{i} " * 50))
        msgs.append(ChatMessage(role="assistant", content=f"reply-{i} " * 50))
    msgs.append(ChatMessage(role="user", content="RECENT-Q " * 50))
    msgs.append(ChatMessage(role="assistant", content="RECENT-A " * 50))
    return msgs


def test_disabled_is_identity_same_objects():
    """token_budget=0 => same list, same objects (byte-identical path)."""
    mgr = ContextWindowManager(token_budget=0)
    msgs = _convo(10)
    out = mgr.apply(msgs)
    assert out == msgs
    assert all(a is b for a, b in zip(out, msgs, strict=True))


def test_under_budget_is_unchanged():
    mgr = ContextWindowManager(token_budget=10_000_000)
    msgs = _convo(10)
    out = mgr.apply(msgs)
    assert [(m.role, m.content) for m in out] == [(m.role, m.content) for m in msgs]


def test_over_budget_keeps_system_and_recent_compresses_middle():
    msgs = _convo(20)
    # Budget well below the full conversation so compression triggers.
    mgr = ContextWindowManager(token_budget=200, keep_recent=4)
    out = mgr.apply(msgs)

    # System tier preserved verbatim at the front.
    assert out[0] is msgs[0]
    # The most-recent keep_recent turns preserved verbatim at the tail.
    assert [(m.role, m.content) for m in out[-4:]] == [
        (m.role, m.content) for m in msgs[-4:]
    ]
    # A single summary placeholder replaced the middle, so the list shrank.
    assert len(out) < len(msgs)
    summaries = [m for m in out if m.content.startswith("[Earlier conversation compressed]")]
    assert len(summaries) == 1
    # No original middle turn text survives.
    assert not any("middle-5" in m.content for m in out)


def test_keep_recent_zero_compresses_all_non_system():
    msgs = _convo(20)
    mgr = ContextWindowManager(token_budget=100, keep_recent=0)
    out = mgr.apply(msgs)
    assert out[0] is msgs[0]
    # Everything after the system tier collapsed to one summary.
    assert len(out) == 2
    assert out[1].content.startswith("[Earlier conversation compressed]")


def test_too_few_turns_to_compress_is_unchanged():
    # Over budget but only system + 2 turns, with keep_recent=4 => nothing safe to drop.
    msgs = [
        ChatMessage(role="system", content="S " * 500),
        ChatMessage(role="user", content="U " * 500),
        ChatMessage(role="assistant", content="A " * 500),
    ]
    mgr = ContextWindowManager(token_budget=1, keep_recent=4)
    out = mgr.apply(msgs)
    assert out == msgs


def test_image_aware_estimation_flat_cost():
    text_only = [ChatMessage(role="user", content="x" * 40)]
    image_part = [
        ChatMessage(
            role="user",
            content=[{"type": "image_url", "image_url": {"url": "data:..."}}],
        )
    ]
    # The flat per-image cost dominates the tiny char estimate.
    img_est = estimate_tokens(image_part)
    assert img_est >= _TOKENS_PER_IMAGE
    assert img_est > estimate_tokens(text_only)


# --- Prefix caching at the adapter boundary --------------------------------

def _transport(capture: dict) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        capture["payload"] = httpx.Request(
            request.method, request.url, content=request.content
        ).read()
        import json as _json

        capture["json"] = _json.loads(request.content)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ok"}}]},
        )

    return httpx.MockTransport(handler)


def _ladder() -> TierLadder:
    return TierLadder(
        tiers=[
            TierConfig(
                provider="openai",
                base_url="https://api.example.com/v1",
                model="m",
                context_window=8192,
            )
        ]
    )


def test_no_prefix_cache_for_non_advertising_provider():
    """OpenAI profile advertises no support => no cache_control key in payload."""
    cap: dict = {}
    llm = OpenAICompatibleLLM(
        ladder=_ladder(), transport=_transport(cap), prefix_cache="on"
    )
    llm.complete([ChatMessage(role="user", content="hi")])
    assert "cache_control" not in str(cap["json"])


def test_prefix_cache_applied_for_advertising_provider(monkeypatch):
    """A capability-advertising fake provider gets breakpoints when posture != off."""

    def _mark(payload: dict) -> dict:
        payload = dict(payload)
        payload["cache_control"] = {"type": "ephemeral"}
        return payload

    caching_profile = ProviderProfile(
        name="openai",
        detect=OPENAI_PROFILE.detect,
        headers=OPENAI_PROFILE.headers,
        models_url=OPENAI_PROFILE.models_url,
        models_extractor=OPENAI_PROFILE.models_extractor,
        chat_url=OPENAI_PROFILE.chat_url,
        build_request=OPENAI_PROFILE.build_request,
        extract_text=OPENAI_PROFILE.extract_text,
        supports_prefix_cache=True,
        mark_prefix_cache=_mark,
    )

    import applicant.adapters.llm.openai_compatible as mod

    monkeypatch.setattr(mod, "get_profile", lambda *a, **k: caching_profile)

    cap: dict = {}
    llm = OpenAICompatibleLLM(
        ladder=_ladder(), transport=_transport(cap), prefix_cache="auto"
    )
    llm.complete([ChatMessage(role="user", content="hi")])
    assert cap["json"].get("cache_control") == {"type": "ephemeral"}

    # ...and OFF disables it even for an advertising provider.
    cap2: dict = {}
    llm_off = OpenAICompatibleLLM(
        ladder=_ladder(), transport=_transport(cap2), prefix_cache="off"
    )
    llm_off.complete([ChatMessage(role="user", content="hi")])
    assert "cache_control" not in cap2["json"]


def test_default_adapter_unchanged_single_shot():
    """Default construction (no manager, default prefix_cache) sends plain payload."""
    cap: dict = {}
    llm = OpenAICompatibleLLM(ladder=_ladder(), transport=_transport(cap))
    res = llm.complete(
        [
            ChatMessage(role="system", content="sys"),
            ChatMessage(role="user", content="hello"),
        ]
    )
    assert res.text == "ok"
    # Both original messages reach the wire unchanged (nothing to compress).
    assert [m["content"] for m in cap["json"]["messages"]] == ["sys", "hello"]
    assert "cache_control" not in str(cap["json"])
