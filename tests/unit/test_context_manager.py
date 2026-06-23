"""Unit tests for the application-layer context manager (FR-MIND-8, FR-MIND-13).

Covers the richer ``ContextManager`` service: threshold-gated middle-turn
compression with parent/child lineage, system + latest + pinned preservation, a
hard-bounded summary, the deterministic + optional-LLM summarizer, and the
provider-gated prefix-cache helper (breakpoints only for a supporting provider,
a clean no-op otherwise). Plus a default-settings byte-identical no-op proof.
"""

from __future__ import annotations

from applicant.application.services.context_manager import (
    SUMMARY_PREFIX,
    ContextManager,
    build_llm_summarizer,
    estimate_tokens,
    prefix_cache_breakpoints,
    provider_supports_prefix_cache,
)
from applicant.ports.driven.llm import ChatMessage


def _convo(n_middle: int) -> list[ChatMessage]:
    """system + n middle turns + a recent tail, each large enough to count."""
    msgs = [ChatMessage(role="system", content="SYSTEM " * 50)]
    for i in range(n_middle):
        msgs.append(ChatMessage(role="user", content=f"middle-{i} " * 50))
        msgs.append(ChatMessage(role="assistant", content=f"reply-{i} " * 50))
    msgs.append(ChatMessage(role="user", content="RECENT-Q " * 50))
    msgs.append(ChatMessage(role="assistant", content="RECENT-A " * 50))
    return msgs


# --- threshold gating / no-op -----------------------------------------------

def test_disabled_threshold_is_identity_same_objects():
    """threshold<=0 (the default) => same list, same objects (no-op path)."""
    mgr = ContextManager(threshold=0)
    msgs = _convo(10)
    result = mgr.compress(msgs)
    assert result.compressed is False
    assert result.turns == msgs
    assert all(a is b for a, b in zip(result.turns, msgs, strict=True))


def test_default_settings_byte_identical_noop():
    """A default-constructed manager never compresses — byte-identical output."""
    mgr = ContextManager()  # all defaults: threshold 0, deterministic summarizer
    msgs = _convo(30)
    result = mgr.compress(msgs)
    assert result.compressed is False
    assert result.turns is not None
    assert [(m.role, m.content) for m in result.turns] == [
        (m.role, m.content) for m in msgs
    ]
    assert all(a is b for a, b in zip(result.turns, msgs, strict=True))


def test_under_threshold_is_unchanged():
    mgr = ContextManager(threshold=10_000_000)
    msgs = _convo(10)
    result = mgr.compress(msgs)
    assert result.compressed is False
    assert result.turns == msgs


def test_too_few_turns_to_compress_is_unchanged():
    msgs = [
        ChatMessage(role="system", content="S " * 500),
        ChatMessage(role="user", content="U " * 500),
        ChatMessage(role="assistant", content="A " * 500),
    ]
    mgr = ContextManager(threshold=1, keep_recent=4)
    result = mgr.compress(msgs)
    assert result.compressed is False
    assert result.turns == msgs


# --- compression + lineage --------------------------------------------------

def test_over_threshold_compresses_middle_keeps_system_and_recent():
    msgs = _convo(20)
    mgr = ContextManager(threshold=200, keep_recent=4)
    result = mgr.compress(msgs)

    assert result.compressed is True
    # System tier preserved verbatim at the front.
    assert result.turns[0] is msgs[0]
    # The most-recent keep_recent turns preserved verbatim at the tail.
    assert [(m.role, m.content) for m in result.turns[-4:]] == [
        (m.role, m.content) for m in msgs[-4:]
    ]
    # Exactly one summary turn replaced the middle, so the list shrank.
    assert len(result.turns) < len(msgs)
    summaries = [m for m in result.turns if m.content.startswith(SUMMARY_PREFIX)]
    assert len(summaries) == 1
    # No original middle turn text survives.
    assert not any("middle-5" in m.content for m in result.turns)


def test_lineage_records_subsumed_children():
    msgs = _convo(20)
    mgr = ContextManager(threshold=200, keep_recent=4)
    result = mgr.compress(msgs)

    lin = result.lineage
    assert lin.compressed is True
    # The parent is the summary turn's position in the OUTPUT list.
    assert result.turns[lin.parent_index].content.startswith(SUMMARY_PREFIX)
    # Children are the ORIGINAL indices of the subsumed middle turns: everything
    # after the system tier (index 0) and before the recent tail (last 4).
    expected = tuple(range(1, len(msgs) - 4))
    assert lin.child_indices == expected
    assert len(lin.child_roles) == len(expected)
    # The subsumed range never includes the system turn or the latest user turn.
    assert 0 not in lin.child_indices
    assert (len(msgs) - 2) not in lin.child_indices  # latest user turn (RECENT-Q)


def test_pinned_turns_preserved_verbatim():
    """A pinned middle turn (e.g. a hard-bounded memory/skills block) is kept."""
    msgs = _convo(20)
    pinned_idx = 5  # a middle turn
    mgr = ContextManager(threshold=200, keep_recent=4)
    result = mgr.compress(msgs, pinned=[pinned_idx])

    assert result.compressed is True
    # The pinned original object survives unchanged in the output.
    assert any(m is msgs[pinned_idx] for m in result.turns)
    # ...and it is NOT listed among the subsumed children.
    assert pinned_idx not in result.lineage.child_indices


def test_summary_is_hard_bounded():
    msgs = _convo(60)  # a lot of middle content
    mgr = ContextManager(threshold=200, keep_recent=2, summary_max_chars=300)
    result = mgr.compress(msgs)
    summary = next(m for m in result.turns if m.content.startswith(SUMMARY_PREFIX))
    assert len(summary.content) <= 300


def test_keep_recent_zero_compresses_all_non_system():
    msgs = _convo(20)
    mgr = ContextManager(threshold=100, keep_recent=0)
    result = mgr.compress(msgs)
    assert result.turns[0] is msgs[0]
    # Everything after the system tier collapsed to one summary.
    assert len(result.turns) == 2
    assert result.turns[1].content.startswith(SUMMARY_PREFIX)


# --- summarizer (deterministic + optional LLM) ------------------------------

def test_injected_llm_summarizer_used_when_configured():
    class _FakeLLM:
        def is_configured(self):
            return True

        def complete(self, messages, **kwargs):
            class _R:
                text = "they discussed the role and the resume"

            return _R()

    summarize = build_llm_summarizer(_FakeLLM())
    mgr = ContextManager(threshold=200, keep_recent=2, summarizer=summarize)
    result = mgr.compress(_convo(20))
    summary = next(m for m in result.turns if m.content.startswith(SUMMARY_PREFIX))
    assert "they discussed the role and the resume" in summary.content


def test_llm_summarizer_falls_back_to_heuristic_when_unconfigured():
    class _Unconfigured:
        def is_configured(self):
            return False

        def complete(self, *a, **k):  # pragma: no cover - must never be called
            raise AssertionError("complete must not be called when unconfigured")

    summarize = build_llm_summarizer(_Unconfigured())
    # Returns the deterministic heuristic; a compress still produces a summary.
    mgr = ContextManager(threshold=200, keep_recent=2, summarizer=summarize)
    result = mgr.compress(_convo(8))
    assert result.compressed is True


def test_llm_summarizer_degrades_per_call_on_error():
    class _FlakyLLM:
        def is_configured(self):
            return True

        def complete(self, *a, **k):
            raise RuntimeError("provider down")

    summarize = build_llm_summarizer(_FlakyLLM())
    mgr = ContextManager(threshold=200, keep_recent=2, summarizer=summarize)
    result = mgr.compress(_convo(8))  # must not raise; degrades to heuristic
    assert result.compressed is True


def test_estimate_tokens_image_aware():
    text_only = [ChatMessage(role="user", content="x" * 40)]
    image_part = [
        ChatMessage(
            role="user",
            content=[{"type": "image_url", "image_url": {"url": "data:..."}}],
        )
    ]
    assert estimate_tokens(image_part) > estimate_tokens(text_only)


# --- provider-gated prefix caching ------------------------------------------

class _Supporting:
    supports_prefix_cache = True

    @staticmethod
    def mark_prefix_cache(payload):
        payload = dict(payload)
        payload["cache_control"] = {"type": "ephemeral"}
        return payload


class _NonSupporting:
    supports_prefix_cache = False

    @staticmethod
    def mark_prefix_cache(payload):  # pragma: no cover - must never be consulted
        raise AssertionError("mark_prefix_cache must not run for a non-supporter")


def test_prefix_cache_supported_emits_breakpoints():
    out = prefix_cache_breakpoints({"messages": []}, _Supporting(), posture="auto")
    assert out.get("cache_control") == {"type": "ephemeral"}


def test_prefix_cache_noop_for_non_supporting_provider():
    payload = {"messages": []}
    out = prefix_cache_breakpoints(payload, _NonSupporting(), posture="on")
    assert out is payload
    assert "cache_control" not in out


def test_prefix_cache_off_is_noop_even_for_supporter():
    payload = {"messages": []}
    out = prefix_cache_breakpoints(payload, _Supporting(), posture="off")
    assert out is payload
    assert "cache_control" not in out


def test_provider_supports_prefix_cache_gating():
    assert provider_supports_prefix_cache(_Supporting(), posture="auto") is True
    assert provider_supports_prefix_cache(_Supporting(), posture="off") is False
    assert provider_supports_prefix_cache(_NonSupporting(), posture="auto") is False
    # An object without the flag (e.g. an Ollama-style profile) => no-op.
    assert provider_supports_prefix_cache(object(), posture="auto") is False
