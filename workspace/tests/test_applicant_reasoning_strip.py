"""Workspace reasoning hygiene — the native chat path must never leak
chain-of-thought (chat unification, requirement 2).

The engine already strips reasoning at its LLM-adapter seam
(``src/applicant/core/rules/reasoning_hygiene.py``); ``workspace/src/
reasoning_strip.py`` is the workspace twin applied at the chat emit seam in
``routes/chat_routes.py``. These tests pin:

* :func:`strip_reasoning` on the exact leaked shapes observed live —
  ``"Here's a thinking process:"`` preambles, ``<think>...</think>`` blocks,
  and ``"Plan:\n1."`` scaffolding — plus the conservative guarantees
  (byte-identical pass-through, idempotency, never emptying a non-empty
  message);
* :class:`ReasoningStreamFilter`'s streaming guarantees (no tag content or
  markup is ever emitted; preamble-shaped heads are withheld until the
  end-of-stream strip; clean text streams through unchanged; late
  reclassification flags ``diverged``);
* the emit-seam wiring in ``routes/chat_routes.py`` (source contract — the
  streaming loops feed deltas through the filter, drop the separate
  ``thinking`` channel, and the rewrite flow no longer carries the
  ``or full_response`` raw-text re-leak).

Hermetic: pure functions + source reads; no app boot, no network.
"""

from __future__ import annotations

import pathlib
import re

from src.reasoning_strip import ReasoningStreamFilter, strip_reasoning

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
CHAT_ROUTES = REPO_ROOT / "workspace" / "routes" / "chat_routes.py"


def _routes_src() -> str:
    return CHAT_ROUTES.read_text(encoding="utf-8")


# ── strip_reasoning: the exact leaked shapes ────────────────────────────────


def test_strips_a_balanced_think_block():
    text = "<think>The user greeted me; keep it warm.</think>Hi! How can I help with your search today?"
    assert strip_reasoning(text) == "Hi! How can I help with your search today?"


def test_strips_a_heres_a_thinking_process_preamble_with_plan_scaffolding():
    """The exact untagged shape seen live from a reasoning model: an explicit
    'Here's a thinking process:' declaration followed by 'Plan:\n1.' style
    scaffolding paragraphs, then the real reply."""
    text = (
        "Here's a thinking process:\n\n"
        "Plan:\n1. Greet the user.\n2. Offer concrete help.\n\n"
        "Drafting: keep it short and warm.\n\n"
        "Hey! I can help with your job search — ask me what needs your attention."
    )
    out = strip_reasoning(text)
    assert out == "Hey! I can help with your job search — ask me what needs your attention."
    assert "thinking process" not in out.lower()
    assert "Plan:" not in out


def test_strips_a_thinking_preamble_bounded_by_a_final_answer_marker():
    text = (
        "Okay, the user has greeted me. I should respond briefly and invite a question. "
        "Final answer: Hello! Tell me what roles you're aiming for and I'll take it from there."
    )
    out = strip_reasoning(text)
    assert out.startswith("Hello! Tell me what roles")
    assert "the user has greeted me" not in out


def test_strips_an_orphan_closing_tag_head():
    text = (
        "The user wants a quick status update, so summarize the campaign briefly."
        "</think>Two applications are waiting on your review — want the details?"
    )
    assert strip_reasoning(text) == (
        "Two applications are waiting on your review — want the details?"
    )


def test_strips_an_unclosed_opener_from_the_tag_onward():
    text = "Here is your answer: 42.<think>should I elaborate more about"
    assert strip_reasoning(text) == "Here is your answer: 42."


def test_normalizes_attribute_carrying_tags():
    text = '<think time="0.42">weighing options…</think>The docx route is the safer fallback.'
    assert strip_reasoning(text) == "The docx route is the safer fallback."


def test_clean_text_passes_through_byte_identical():
    for text in (
        "A perfectly ordinary reply with no reasoning markers at all.",
        '{"a": 1, "b": "x < y", "c": [1, 2, 3]}',
        "Some code: `if (a < b) { return a; }` — and a claim that 1 < 2.",
    ):
        assert strip_reasoning(text) == text


def test_idempotent_on_every_shape():
    samples = [
        "<think>plan</think>The reply survives a second pass unchanged, guaranteed.",
        "Here's a thinking process:\n\nPlan:\n1. x\n\nThe real reply is right here and long enough.",
        "reasoning head</think>The visible remainder is long enough to keep around.",
        "Clean text stays clean.",
    ]
    for text in samples:
        once = strip_reasoning(text)
        assert strip_reasoning(once) == once


def test_never_empties_a_non_empty_message():
    # A reply that is 100% reasoning collapses to the markup-free text rather
    # than an empty bubble (the engine's conservative never-empty rule).
    out = strip_reasoning("<think>only reasoning in here</think>")
    assert out == "only reasoning in here"
    assert strip_reasoning("<think></think>") == ""  # nothing but markup + no prose


# ── ReasoningStreamFilter: streaming guarantees ─────────────────────────────


def test_stream_filter_never_emits_tag_content_or_markup():
    f = ReasoningStreamFilter()
    emitted = ""
    for chunk in ["<thi", "nk>secret step one; ", "secret step two</th", "ink>Hello! Here is the clean reply."]:
        emitted += f.feed(chunk)
    emitted += f.flush()
    assert emitted == "Hello! Here is the clean reply."
    assert "secret" not in emitted and "<" not in emitted
    assert f.visible_text == emitted
    assert not f.diverged


def test_stream_filter_streams_clean_text_through_unchanged():
    f = ReasoningStreamFilter()
    chunks = [
        "This is a perfectly normal reply that streams straight through without any reasoning markers. ",
        "It keeps going with more useful text,",
        " and then it ends.",
    ]
    emitted = "".join(f.feed(c) for c in chunks) + f.flush()
    assert emitted == "".join(chunks)
    assert not f.diverged


def test_stream_filter_withholds_a_preamble_shaped_head_until_flush():
    f = ReasoningStreamFilter()
    live = [
        f.feed(
            "Here's a thinking process: consider what the user actually needs and "
            "outline the reply before writing anything at all. "
        ),
        f.feed("Final answer: You have three new matches today — open your digest to review them."),
    ]
    assert live == ["", ""], "a reasoning-shaped head must not stream live"
    tail = f.flush()
    assert tail.startswith("You have three new matches today")
    assert f.visible_text == tail
    assert not f.diverged


def test_stream_filter_flags_divergence_when_a_late_orphan_close_arrives():
    f = ReasoningStreamFilter()
    head = (
        "I considered the user's history carefully and weighed several options in detail "
        "before deciding on the best possible answer for this situation. "
    )
    shown = f.feed(head)
    assert shown  # the head streamed live (nothing marked it as reasoning yet)
    f.feed("</think>Here is the clean final answer, with enough substance to stand on its own.")
    f.flush()
    assert f.diverged, "late reclassification must flag the divergence"
    assert f.visible_text == (
        "Here is the clean final answer, with enough substance to stand on its own."
    ), "the settled visible text must be the clean reply only"


def test_stream_filter_drops_a_reasoning_only_segment_at_a_round_boundary():
    # Agent-mode shape: the model thinks, never closes the tag, then calls a
    # tool. The segment flush (mid-message semantics, never_empty=False) must
    # neither emit the think content nor let it swallow the next round.
    f = ReasoningStreamFilter()
    out = f.feed("<think>I should call the search tool with the user's terms")
    out += f.flush(never_empty=False)
    assert out == ""
    assert f.visible_text == ""


def test_stream_filter_keeps_whole_message_never_empty_semantics_by_default():
    # A stand-alone reply that is 100% reasoning collapses to the markup-free
    # text (mirror of the engine's rule) rather than a blank bubble.
    f = ReasoningStreamFilter()
    f.feed("<think>only reasoning in here</think>")
    assert f.flush() == "only reasoning in here"


# ── emit-seam wiring in routes/chat_routes.py (source contract) ─────────────


def test_chat_stream_loops_feed_deltas_through_the_filter():
    src = _routes_src()
    assert "from src.reasoning_strip import ReasoningStreamFilter, strip_reasoning" in src
    # Both streaming loops (chat mode + agent mode) build a filter and feed
    # every content delta through it instead of forwarding the raw chunk.
    assert src.count("ReasoningStreamFilter()") >= 3  # chat mode + agent mode (init & per-segment) + rewrite
    assert src.count('_rfilter.feed(data["delta"])') >= 3


def test_separate_channel_reasoning_is_dropped_not_forwarded():
    """Deltas flagged ``thinking: true`` (reasoning_content) must be dropped at
    the emit seam on every streaming path — never yielded to the browser."""
    src = _routes_src()
    drops = re.findall(r'if data\.get\("thinking"\):\n(?:\s*#[^\n]*\n)*\s*continue', src)
    assert len(drops) >= 3, (
        "expected the thinking-channel drop guard in the chat-mode, agent-mode "
        "and rewrite streaming loops"
    )


def test_the_rewrite_flow_no_longer_reverts_to_raw_text():
    """The old ``strip_thinking(full_response).strip() or full_response``
    fallback re-leaked a reply that was 100% reasoning. The rewrite flow now
    settles on the stream filter's clean text with no raw-text fallback."""
    src = _routes_src()
    assert "or full_response" not in src
    assert "from src.research_utils import strip_thinking" not in src
    assert "_rfilter.visible_text.strip()" in src


def test_non_streaming_chat_reply_is_stripped_before_save_and_response():
    src = _routes_src()
    assert 'reply = strip_reasoning(reply or "")' in src
    # The strip happens BEFORE the persisted copy is prepared, so metadata can
    # never carry the scratchpad either.
    assert src.index('reply = strip_reasoning(reply or "")') < src.index(
        "clean_thinking_for_save(reply"
    )


def test_divergence_settles_with_a_content_replace_event():
    """When the clean end-of-stream text diverges from what streamed live, the
    chat-mode loop must tell the client to replace the rendered text."""
    src = _routes_src()
    assert '"type": "content_replace"' in src
    assert "_rfilter.diverged" in src
