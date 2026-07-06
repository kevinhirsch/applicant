"""LLM output hygiene — no chain-of-thought ever reaches user-visible text.

Covers the pure normalizer (``core/rules/reasoning_hygiene.strip_reasoning``:
tag variants, unclosed/orphan tags, untagged thinking-process preambles,
idempotency, the never-delete-everything guard, no-overstrip passthrough) and
the adapter seam (``provider_profiles`` extract_text: inline stripping plus the
separate ``reasoning`` / ``reasoning_content`` / ``thinking`` channels being
dropped, never concatenated). Includes regression tests using the EXACT leaked
shapes observed live with local Qwen / OpenRouter-class reasoning models.
"""

from __future__ import annotations

from applicant.adapters.llm.provider_profiles import OLLAMA_PROFILE, OPENAI_PROFILE
from applicant.core.rules.reasoning_hygiene import strip_reasoning

ANSWER = "Hi! I'm Applicant, the agent that runs your job search. What should we tackle first?"


# ---------------------------------------------------------------------------
# Tagged blocks — the common reasoning-model wire shapes
# ---------------------------------------------------------------------------


class TestTagBlocks:
    def test_think_block_removed(self):
        assert strip_reasoning(f"<think>The user greeted me. Plan a reply.</think>{ANSWER}") == ANSWER

    def test_thinking_block_removed(self):
        assert strip_reasoning(f"<thinking>step 1... step 2...</thinking>\n{ANSWER}") == ANSWER

    def test_reasoning_block_removed(self):
        assert strip_reasoning(f"<reasoning>hmm, let me plan</reasoning>{ANSWER}") == ANSWER

    def test_case_insensitive_and_spaced_tags(self):
        assert strip_reasoning(f"< THINK >secret plan</ THINK >{ANSWER}") == ANSWER

    def test_multiline_block_removed(self):
        text = f"<think>\nline one\nline two\n</think>\n\n{ANSWER}"
        assert strip_reasoning(text) == ANSWER

    def test_multiple_blocks_removed(self):
        text = f"<think>a</think>{ANSWER}<think>b</think>"
        assert strip_reasoning(text) == ANSWER

    def test_short_answer_after_balanced_block_survives_without_leak(self):
        # A balanced block is unambiguous: even a tiny surviving answer is the
        # answer — the reasoning must NOT come back via the too-short fallback.
        out = strip_reasoning("<think>very long hidden deliberation about greetings</think>Hi!")
        assert out == "Hi!"
        assert "deliberation" not in out

    def test_block_only_message_falls_back_to_detagged_text(self):
        # Whole message is one think block: never return empty — return the
        # original minus the tag markup.
        out = strip_reasoning("<think>the model never wrote an answer</think>")
        assert out == "the model never wrote an answer"


class TestMalformedTags:
    def test_orphan_closing_tag_drops_leading_reasoning(self):
        # Template swallowed the opener: reasoning runs from the start to </think>.
        text = f"The user greeted me, so I will introduce myself briefly.</think>{ANSWER}"
        assert strip_reasoning(text) == ANSWER

    def test_orphan_close_with_tiny_remainder_keeps_text_minus_markup(self):
        # Dropping the head would leave <20 chars — too risky; only the markup goes.
        out = strip_reasoning("some text</think>Hi!")
        assert out == "some textHi!"
        assert "</think>" not in out

    def test_unclosed_opener_at_start_returns_detagged_text(self):
        # <think> at position 0, never closed: everything is reasoning; deleting
        # it all would empty the reply, so only the markup is removed.
        text = "<think>partial chain of thought that ran out of tokens"
        assert strip_reasoning(text) == "partial chain of thought that ran out of tokens"

    def test_trailing_unclosed_opener_keeps_answer_drops_tail(self):
        out = strip_reasoning(f"{ANSWER}<think>oh wait, should I also mention")
        assert out == ANSWER
        assert "oh wait" not in out

    def test_trailing_unclosed_opener_after_short_answer(self):
        out = strip_reasoning("Done!<think>now, reflecting on what else the user might need")
        assert out == "Done!"


# ---------------------------------------------------------------------------
# Untagged thinking-process preambles (misconfigured templates)
# ---------------------------------------------------------------------------


class TestUntaggedPreambles:
    def test_lead_without_boundary_is_left_alone(self):
        # Conservative: a "The user…" narration with NO final-answer boundary is
        # ambiguous — never guess at where the answer starts.
        text = "The user has greeted me. I should reply warmly and ask a question."
        assert strip_reasoning(text) == text

    def test_boundary_takes_text_after_last_marker(self):
        text = (
            "The user asked about resumes. Plan: explain the redline.\n"
            f"Final answer: {ANSWER}"
        )
        assert strip_reasoning(text) == ANSWER

    def test_horizontal_rule_boundary(self):
        text = f"Okay, the user wants a summary. Draft it mentally.\n---\n{ANSWER}"
        assert strip_reasoning(text) == ANSWER

    def test_normal_reply_never_touched(self):
        text = "You're all set! I found 4 roles today and prepared 2 redlines for review."
        assert strip_reasoning(text) == text

    def test_possessive_user_reference_is_not_a_lead(self):
        text = "The user's profile matches this role well: strong Python and five years of backend work."
        assert strip_reasoning(text) == text

    def test_final_answer_mention_without_lead_is_untouched(self):
        # Boundary markers only apply when the message STARTS with a reasoning lead.
        text = "Final answer: yes, the salary floor is applied to every search."
        assert strip_reasoning(text) == text


# ---------------------------------------------------------------------------
# Regression — the EXACT leaked shapes seen live (P0 transcript evidence)
# ---------------------------------------------------------------------------


LEAKED_GREETING = (
    "The user has greeted me. I should introduce myself and offer help. "
    "Plan: 1. Greet them back warmly. 2. State what I can do. 3. Invite a next step. "
    "Drafting: something friendly but concise. "
    "Refinement: cut the filler, keep it warm. "
    "Final Polish: Hey! I'm Applicant — I run your job search around the clock. "
    "Want me to show you today's matches?"
)

LEAKED_THINKING_PROCESS = (
    "Here's a thinking process: 1. Analyze the User's Input: they want to know what "
    "I need from them. 2. List the essentials that are still missing. 3. Keep it short.\n\n"
    "To get started I need your name, email, phone, and current job title — plus a resume."
)


class TestLiveLeakRegression:
    def test_greeting_leak_stripped_to_final_polish(self):
        out = strip_reasoning(LEAKED_GREETING)
        assert out.startswith("Hey! I'm Applicant")
        for marker in ("Plan:", "Drafting:", "Refinement:", "Final Polish:", "The user has greeted me"):
            assert marker not in out

    def test_thinking_process_leak_stripped_to_answer(self):
        out = strip_reasoning(LEAKED_THINKING_PROCESS)
        assert out.startswith("To get started I need")
        assert "thinking process" not in out.lower()
        assert "Analyze the User's Input" not in out

    def test_leaked_shapes_via_openai_profile(self):
        for leaked, must_not in (
            (LEAKED_GREETING, "Plan:"),
            (LEAKED_THINKING_PROCESS, "thinking process"),
            (f"<think>hidden plan</think>{ANSWER}", "<think"),
        ):
            raw = {"choices": [{"message": {"role": "assistant", "content": leaked}}]}
            out = OPENAI_PROFILE.extract_text(raw)
            assert must_not.lower() not in out.lower()
            assert len(out) > 20


# ---------------------------------------------------------------------------
# Idempotency + streaming-shaped input
# ---------------------------------------------------------------------------


class TestIdempotencyAndStreaming:
    def test_idempotent_on_all_primary_shapes(self):
        shapes = [
            f"<think>plan</think>{ANSWER}",
            f"reasoning head goes here</think>{ANSWER}",
            f"{ANSWER}<think>trailing rumination",
            "<think>only reasoning, never closed",
            LEAKED_GREETING,
            LEAKED_THINKING_PROCESS,
            ANSWER,
            "",
        ]
        for shape in shapes:
            once = strip_reasoning(shape)
            assert strip_reasoning(once) == once, f"not idempotent for: {shape[:40]!r}"

    def test_streaming_shaped_chunks_assemble_clean(self):
        # A streamed reply splits tags across deltas; the engine buffers deltas
        # into one string before display, so stripping the assembled text must
        # remove the reasoning exactly as if it had arrived in one chunk.
        chunks = ["<th", "ink>step 1: gree", "t the user</th", "ink>", ANSWER[:20], ANSWER[20:]]
        assembled = "".join(chunks)
        assert strip_reasoning(assembled) == ANSWER

    def test_streaming_chunks_with_orphan_close(self):
        chunks = ["planning the reply now", "</think>\n", ANSWER]
        assert strip_reasoning("".join(chunks)) == ANSWER


# ---------------------------------------------------------------------------
# No-overstrip guarantees (scoring rationales, JSON, tool args, math)
# ---------------------------------------------------------------------------


class TestNoOverstrip:
    def test_json_payload_untouched(self):
        payload = '{"score": 82, "rationale": "strong match on Python and infra"}'
        assert strip_reasoning(payload) == payload

    def test_comparison_operators_untouched(self):
        text = "If salary < 100k and level > mid, I skip the role per your criteria."
        assert strip_reasoning(text) == text

    def test_html_ish_but_non_reasoning_tags_untouched(self):
        text = "Use <b>bold</b> in the cover letter sparingly."
        assert strip_reasoning(text) == text

    def test_plain_short_message_untouched(self):
        assert strip_reasoning("Done!") == "Done!"

    def test_empty_and_none_like(self):
        assert strip_reasoning("") == ""

    def test_never_returns_empty_for_nonempty_input(self):
        leaks = [
            "<think>a</think>",
            "<thinking>abc",
            "abc</reasoning>",
            "<think></think>x",
        ]
        for text in leaks:
            assert strip_reasoning(text).strip() != "" or not text.strip()


# ---------------------------------------------------------------------------
# Adapter seam — separate reasoning channels are DROPPED, never concatenated
# ---------------------------------------------------------------------------


class TestAdapterReasoningChannels:
    def test_openrouter_reasoning_field_never_concatenated(self):
        raw = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": ANSWER,
                        "reasoning": "I should greet the user and plan my reply.",
                    }
                }
            ]
        }
        out = OPENAI_PROFILE.extract_text(raw)
        assert out == ANSWER
        assert "plan my reply" not in out

    def test_reasoning_content_field_never_concatenated(self):
        raw = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": ANSWER,
                        "reasoning_content": "hidden deliberation",
                    }
                }
            ]
        }
        assert OPENAI_PROFILE.extract_text(raw) == ANSWER

    def test_empty_content_with_reasoning_field_yields_empty_not_reasoning(self):
        # When the model spent its whole budget thinking, content is empty and the
        # reasoning channel holds CoT. The user-facing text must NOT fall back to
        # it — an empty reply triggers the caller's deterministic fallback instead.
        raw = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "reasoning": "endless deliberation that never concluded",
                    }
                }
            ]
        }
        assert OPENAI_PROFILE.extract_text(raw) == ""

    def test_ollama_thinking_channel_dropped_and_inline_tags_stripped(self):
        raw = {
            "message": {
                "role": "assistant",
                "content": f"<think>local qwen rumination</think>{ANSWER}",
                "thinking": "separate thinking channel",
            }
        }
        out = OLLAMA_PROFILE.extract_text(raw)
        assert out == ANSWER
        assert "rumination" not in out
        assert "separate thinking channel" not in out

    def test_tool_call_arguments_fallback_passes_verbatim(self):
        args = '{"query": "backend roles", "limit": 5}'
        raw = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {"function": {"name": "search", "arguments": args}}
                        ],
                    }
                }
            ]
        }
        assert OPENAI_PROFILE.extract_text(raw) == args
