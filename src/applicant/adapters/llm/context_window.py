"""Context-window management for the LLM adapter (FR-MIND-8, FR-MIND-13).

A pure, deterministic helper that bounds the message list handed to a provider so
a long-running multi-turn conversation does not grow without limit. When the
estimated token count crosses a configured budget it **keeps the system tier and
the most recent turns intact and compresses/evicts the middle turns** into a
single summary placeholder — mirroring the upstream context-compressor approach.

This lives in ``adapters/llm`` (not ``application`` or ``core``) on purpose: it
only depends on :class:`~applicant.ports.driven.llm.ChatMessage` (a lower layer),
and it is consumed by the LLM adapter that sits in this same layer — so it never
violates the hexagonal boundary (``app > application > adapters > ports > core``).

Design notes
------------
* **Default OFF / no-op.** When ``token_budget`` is ``0`` (or falsy) the manager
  returns the *same* message objects in the *same* order — byte-identical to the
  un-managed path — so existing behavior is unchanged until an operator opts in.
* **Image-aware estimation.** ``ChatMessage.content`` is typed ``str`` today, but
  a defensive estimator also handles a list of multimodal *parts* (text/image
  dicts) so the helper keeps working if/when content becomes multimodal. Each
  image part counts as a flat ~1500 tokens (the upstream heuristic) rather than
  by character length.
* **Deterministic.** No IO, no randomness, no clock — unit-testable in isolation.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from applicant.ports.driven.llm import ChatMessage

#: Rough chars-per-token heuristic, matching the adapter's local estimate. Kept in
#: sync with ``openai_compatible._CHARS_PER_TOKEN`` so the budget math agrees.
_CHARS_PER_TOKEN = 4

#: Flat per-image token cost for multimodal parts (mirrors the upstream approach —
#: an image is billed as a fixed block rather than by serialized length).
_TOKENS_PER_IMAGE = 1500

#: How many of the most-recent (non-system) turns are always preserved verbatim.
_DEFAULT_KEEP_RECENT = 4

#: Marker text for the synthesized summary placeholder, so callers/tests can
#: detect that compression occurred without coupling to the exact prose.
_SUMMARY_PREFIX = "[Earlier conversation compressed]"


def _content_tokens(content: Any) -> int:
    """Estimate tokens for one message's content (text or multimodal parts).

    A plain string is charged by character length; a list of parts is summed,
    with image parts charged a flat per-image cost (image-aware estimation).
    """
    if isinstance(content, str):
        return len(content) // _CHARS_PER_TOKEN
    if isinstance(content, Iterable):
        total = 0
        for part in content:
            if isinstance(part, dict):
                ptype = str(part.get("type", "")).lower()
                if "image" in ptype:
                    total += _TOKENS_PER_IMAGE
                    continue
                text = part.get("text")
                if isinstance(text, str):
                    total += len(text) // _CHARS_PER_TOKEN
                    continue
                total += len(str(part)) // _CHARS_PER_TOKEN
            elif isinstance(part, str):
                total += len(part) // _CHARS_PER_TOKEN
        return total
    return len(str(content)) // _CHARS_PER_TOKEN


def estimate_tokens(messages: Sequence[ChatMessage]) -> int:
    """Image-aware token estimate for a message list (deterministic, IO-free)."""
    return sum(len(m.role) // _CHARS_PER_TOKEN + _content_tokens(m.content) for m in messages)


@dataclass(frozen=True)
class ContextWindowManager:
    """Bound a message list to a token budget by compressing middle turns.

    Parameters
    ----------
    token_budget:
        Compress only when the estimated token count exceeds this many tokens.
        ``0`` (the default) disables the manager entirely — :meth:`apply` becomes
        an identity (the very same message objects come back).
    keep_recent:
        Number of most-recent non-system turns always preserved verbatim.
    """

    token_budget: int = 0
    keep_recent: int = _DEFAULT_KEEP_RECENT

    @property
    def enabled(self) -> bool:
        return self.token_budget > 0

    def apply(self, messages: Sequence[ChatMessage]) -> list[ChatMessage]:
        """Return a (possibly) trimmed copy bounded to ``token_budget``.

        Disabled, under budget, or with nothing safe to compress => the input is
        returned unchanged (same objects, same order). Otherwise the middle turns
        (everything between the leading system tier and the most recent
        ``keep_recent`` turns) collapse into one summary placeholder.
        """
        msgs = list(messages)
        if not self.enabled or estimate_tokens(msgs) <= self.token_budget:
            return msgs

        # Partition: leading system tier (kept), middle (compressible), recent tail.
        lead = 0
        while lead < len(msgs) and msgs[lead].role == "system":
            lead += 1
        system_tier = msgs[:lead]
        rest = msgs[lead:]

        keep = max(0, self.keep_recent)
        if len(rest) <= keep:
            # Not enough middle turns to compress without touching system/recent.
            return msgs

        recent = rest[len(rest) - keep:] if keep else []
        middle = rest[: len(rest) - keep] if keep else rest
        if not middle:
            return msgs

        summary = ChatMessage(
            role="system",
            content=(
                f"{_SUMMARY_PREFIX}: {len(middle)} earlier message(s) were summarized "
                "to stay within the model's context budget. Recent turns and the "
                "original instructions are preserved verbatim."
            ),
        )
        return [*system_tier, summary, *recent]


__all__ = [
    "ContextWindowManager",
    "estimate_tokens",
]
