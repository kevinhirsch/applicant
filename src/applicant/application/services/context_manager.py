"""Context manager — middle-turn compression + provider-gated prefix caching (FR-MIND-8).

A long-running multi-turn reasoning loop grows its message list without bound,
which is both slow and a token furnace (FR-MIND-13). This application service bounds
that growth: once the estimated context crosses a configured threshold it
**summarizes/evicts the MIDDLE turns** — keeping the system tier, the most-recent
turns, and any **pinned** turns intact — into a single, hard-bounded summary turn,
and records **parent/child lineage** so the compression is traceable (which earlier
turns a summary subsumes).

This is a **cost/efficiency optimization, not a correctness change** (FR-MIND-8):

* **Default OFF / no-op.** With ``threshold <= 0`` (the configured default) or while
  under budget, :meth:`compress` returns the input turns **unchanged** (same objects,
  same order) — byte-identical to the un-managed path. Existing call sites and tests
  are unaffected until an operator opts in.
* **Never drops a safety block.** The leading system tier, the latest user turn, and
  any turn marked ``pinned`` (e.g. the hard-bounded memory/skills blocks, FR-MIND-13)
  are ALWAYS preserved verbatim. Compression is **advisory context only** — it cannot
  change any guard or authorization (FR-MIND-11): the summary it emits is plain
  recap text and confers no authority.
* **Deterministic + hermetic.** Like :mod:`curation_service`, summarization runs
  through an **injected callable** that defaults to a trivial, deterministic
  heuristic (no LLM, no IO, no clock), so the hermetic lane is green with no model
  wired. Production MAY inject a cheap-model summarizer (FR-MIND-13) via
  :func:`build_llm_summarizer`; per-call LLM errors degrade to the heuristic.

Hexagonal placement: this is an **application service**. It depends only on the
:mod:`~applicant.ports.driven.llm` port types (a lower layer) and takes its
threshold/settings as constructor params (duck-typed) — it never imports
``app.config``, so the layer contract (``app > application > adapters > ports >
core``) stays intact.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from applicant.observability.logging import get_logger
from applicant.ports.driven.llm import ChatMessage

log = get_logger(__name__)

#: Rough chars-per-token heuristic, kept in sync with the LLM adapter's local
#: estimate so the threshold math agrees across layers (FR-MIND-8).
_CHARS_PER_TOKEN = 4

#: Flat per-image token cost for multimodal parts (an image is billed as a fixed
#: block rather than by serialized length — the upstream heuristic).
_TOKENS_PER_IMAGE = 1500

#: How many of the most-recent (non-system, non-pinned) turns are always kept.
_DEFAULT_KEEP_RECENT = 4

#: Hard ceiling on the synthesized summary's length (chars). The summary is
#: advisory recap only and must never reintroduce an unbounded prompt (FR-MIND-13).
_DEFAULT_SUMMARY_MAX_CHARS = 1500

#: Stable marker prefix so callers/tests can detect that compression occurred
#: without coupling to the exact prose.
SUMMARY_PREFIX = "[Earlier conversation summarized]"


def _content_tokens(content: Any) -> int:
    """Estimate tokens for one message's content (text or multimodal parts)."""
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


def estimate_tokens(turns: Sequence[ChatMessage]) -> int:
    """Image-aware token estimate for a turn list (deterministic, IO-free)."""
    return sum(
        len(t.role) // _CHARS_PER_TOKEN + _content_tokens(t.content) for t in turns
    )


def _as_text(content: Any) -> str:
    """Flatten message content to plain text for the deterministic summary."""
    if isinstance(content, str):
        return content
    if isinstance(content, Iterable):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict):
                ptype = str(part.get("type", "")).lower()
                if "image" in ptype:
                    parts.append("[image]")
                elif isinstance(part.get("text"), str):
                    parts.append(part["text"])
            elif isinstance(part, str):
                parts.append(part)
        return " ".join(parts)
    return str(content)


@dataclass(frozen=True)
class CompressionLineage:
    """Parent/child lineage for one compression (FR-MIND-8 traceability).

    ``parent_index`` is where the synthesized summary turn sits in the OUTPUT list;
    ``child_indices`` are the positions, in the ORIGINAL turn list, of the middle
    turns the summary subsumes. ``child_roles`` records their roles for an honest
    audit trail. ``compressed`` is False for a no-op pass (nothing was subsumed).
    """

    parent_index: int
    child_indices: tuple[int, ...] = ()
    child_roles: tuple[str, ...] = ()
    compressed: bool = False


@dataclass(frozen=True)
class CompressionResult:
    """Outcome of one :meth:`ContextManager.compress` pass.

    ``turns`` is the (possibly) trimmed message list to send to the provider;
    ``lineage`` records which earlier turns the summary subsumes. When nothing was
    compressed, ``turns`` is the input unchanged and ``lineage.compressed`` is False.
    """

    turns: list[ChatMessage]
    lineage: CompressionLineage

    @property
    def compressed(self) -> bool:
        return self.lineage.compressed


def _default_summarizer(turns: Sequence[ChatMessage]) -> str:
    """Trivial deterministic recap of the middle turns (no LLM, no IO).

    Good enough for the hermetic lane and the lineage tests. Production MAY inject
    a cheap-model summarizer (:func:`build_llm_summarizer`, FR-MIND-13).
    """
    bits: list[str] = []
    for t in turns:
        snippet = " ".join(_as_text(t.content).split())
        if snippet:
            bits.append(f"{t.role}: {snippet}")
    joined = " | ".join(bits)
    return joined


def build_llm_summarizer(
    llm,
    *,
    start_tier: int = 1,
    max_chars: int = _DEFAULT_SUMMARY_MAX_CHARS,
) -> Callable[[Sequence[ChatMessage]], str]:
    """Build a CHEAP, OPTIONAL LLM-backed middle-turn summarizer (FR-MIND-8/-13).

    Mirrors :func:`curation_service.build_llm_summarizer`. Returns a callable with
    the same shape as :func:`_default_summarizer`, defensive by construction:

    * ``llm`` is ``None`` / not configured => returns the heuristic directly (the
      hermetic lane stays green with NO model wired, behavior is today's heuristic).
    * Per call, any LLM error degrades to the heuristic for THAT pass rather than
      raising, so one flaky completion never breaks the reasoning loop.
    """
    if llm is None:
        return _default_summarizer
    try:
        if not llm.is_configured():
            return _default_summarizer
    except Exception:  # pragma: no cover - defensive: treat as not configured
        return _default_summarizer

    _system = (
        "You compress the middle of a long assistant conversation into a brief, "
        "factual recap so it fits the model's context budget. Reply with a few short "
        "sentences capturing only what later turns need to know. Recap procedure and "
        "facts already stated — never invent new facts about the user, and never "
        "claim authority to submit or to bypass any review."
    )

    def _summarize(turns: Sequence[ChatMessage]) -> str:
        transcript = "\n".join(
            f"{t.role}: {_as_text(t.content)}" for t in turns
        )
        user = f"Summarize these earlier turns:\n{transcript}"
        try:
            result = llm.complete(
                [
                    ChatMessage(role="system", content=_system),
                    ChatMessage(role="user", content=user),
                ],
                start_tier=start_tier,
                max_tokens=max(1, max_chars // _CHARS_PER_TOKEN),
            )
        except Exception as exc:  # degrade to heuristic for THIS pass, never raise
            log.debug("context_summarizer_degraded", error=str(exc))
            return _default_summarizer(turns)
        text = (getattr(result, "text", "") or "").strip()
        return text or _default_summarizer(turns)

    return _summarize


@dataclass
class ContextManager:
    """Bound a multi-turn message list by compressing the middle (FR-MIND-8).

    Parameters
    ----------
    threshold:
        Compress only when the estimated token count exceeds this many tokens.
        ``<= 0`` (the default) DISABLES the manager entirely — :meth:`compress`
        becomes an identity (the very same turn objects come back).
    keep_recent:
        Number of most-recent non-system, non-pinned turns always kept verbatim.
    summary_max_chars:
        Hard ceiling on the synthesized summary text (advisory recap stays bounded).
    summarizer:
        Callable mapping the subsumed middle turns to recap text. Defaults to a
        deterministic heuristic; production MAY inject a cheap-model summarizer.
    """

    threshold: int = 0
    keep_recent: int = _DEFAULT_KEEP_RECENT
    summary_max_chars: int = _DEFAULT_SUMMARY_MAX_CHARS
    summarizer: Callable[[Sequence[ChatMessage]], str] = field(
        default=_default_summarizer
    )

    @property
    def enabled(self) -> bool:
        return self.threshold > 0

    def compress(
        self,
        turns: Sequence[ChatMessage],
        *,
        pinned: Sequence[int] | None = None,
    ) -> CompressionResult:
        """Compress middle turns once context crosses ``threshold`` (FR-MIND-8).

        ``pinned`` are 0-based indices into ``turns`` that must be preserved verbatim
        wherever they sit (e.g. the hard-bounded memory/skills blocks, FR-MIND-13) —
        on top of the always-kept system tier and most-recent ``keep_recent`` turns.

        Disabled, under budget, or with nothing safe to compress => the input is
        returned unchanged (same objects, same order) and ``lineage.compressed`` is
        False. Otherwise the eligible middle turns collapse into ONE bounded summary
        turn and the lineage records which originals it subsumes.
        """
        msgs = list(turns)
        pin = {i for i in (pinned or ()) if 0 <= i < len(msgs)}

        noop = CompressionResult(
            turns=msgs,
            lineage=CompressionLineage(parent_index=-1, compressed=False),
        )
        if not self.enabled or estimate_tokens(msgs) <= self.threshold:
            return noop

        # Leading system tier (always kept). The latest user/assistant turns and any
        # pinned turn are protected below; everything else in between is compressible.
        lead = 0
        while lead < len(msgs) and msgs[lead].role == "system":
            lead += 1

        keep = max(0, self.keep_recent)
        recent_start = len(msgs) - keep if keep else len(msgs)
        recent_start = max(recent_start, lead)

        # A middle turn is eligible iff it is past the system tier, before the recent
        # tail, and not individually pinned (a safety block stays put — FR-MIND-13).
        middle_indices = [
            i for i in range(lead, recent_start) if i not in pin
        ]
        if not middle_indices:
            return noop

        middle_turns = [msgs[i] for i in middle_indices]
        summary_text = self._bounded_summary(middle_turns)

        # Reassemble: system tier + summary + (pinned-in-middle, in order) + recent
        # tail. Pinned middle turns are reinserted verbatim so no safety block is
        # ever dropped; only the unpinned middle is replaced by the summary.
        first_middle = middle_indices[0]
        summary_turn = ChatMessage(role="system", content=summary_text)

        out: list[ChatMessage] = []
        parent_index = -1
        inserted_summary = False
        for i, m in enumerate(msgs):
            if lead <= i < recent_start and i not in pin:
                if not inserted_summary:
                    parent_index = len(out)
                    out.append(summary_turn)
                    inserted_summary = True
                continue  # subsumed by the summary
            out.append(m)

        lineage = CompressionLineage(
            parent_index=parent_index if parent_index >= 0 else first_middle,
            child_indices=tuple(middle_indices),
            child_roles=tuple(msgs[i].role for i in middle_indices),
            compressed=True,
        )
        return CompressionResult(turns=out, lineage=lineage)

    def _bounded_summary(self, middle_turns: Sequence[ChatMessage]) -> str:
        """Run the injected summarizer and hard-bound the result (FR-MIND-13)."""
        try:
            recap = (self.summarizer(middle_turns) or "").strip()
        except Exception as exc:  # pragma: no cover - defensive, never raise upward
            log.debug("context_summary_failed", error=str(exc))
            recap = _default_summarizer(middle_turns)
        n = len(middle_turns)
        body = (
            f"{SUMMARY_PREFIX} ({n} earlier turn(s) condensed to stay within the "
            f"model's context budget): {recap}"
        )
        cap = max(len(SUMMARY_PREFIX) + 1, self.summary_max_chars)
        if len(body) > cap:
            body = body[: cap - 1].rstrip() + "…"
        return body


__all__ = [
    "ChatMessage",
    "CompressionLineage",
    "CompressionResult",
    "ContextManager",
    "SUMMARY_PREFIX",
    "build_llm_summarizer",
    "estimate_tokens",
    "prefix_cache_breakpoints",
    "provider_supports_prefix_cache",
]


# ---------------------------------------------------------------------------
# Provider-gated prefix caching (the cache_control analogue) — FR-MIND-8
# ---------------------------------------------------------------------------

def provider_supports_prefix_cache(profile: Any, *, posture: str = "auto") -> bool:
    """True iff prefix-cache breakpoints should be emitted for this provider.

    ``profile`` is any object exposing a ``supports_prefix_cache`` flag (the LLM
    adapter's :class:`ProviderProfile`). Gating, NOT hardcoded to a single vendor:

    * ``posture == "off"`` => never (operator opted out).
    * else => only when the resolved provider advertises support.

    Local Ollama and OpenAI-compatible cloud advertise no support, so this returns
    False for them regardless of posture — a clean no-op for those lanes (FR-MIND-8).
    """
    if (posture or "auto").strip().lower() == "off":
        return False
    return bool(getattr(profile, "supports_prefix_cache", False))


def prefix_cache_breakpoints(
    payload: dict[str, Any],
    profile: Any,
    *,
    posture: str = "auto",
) -> dict[str, Any]:
    """Apply provider prefix-cache breakpoints to ``payload`` when supported.

    A clean no-op (returns ``payload`` unchanged, same object) unless the posture
    allows it AND the provider advertises support — then it delegates to the
    provider profile's ``mark_prefix_cache`` (the Anthropic ``cache_control``
    analogue) to stamp the stable prefix. Degrades to the unchanged payload if the
    profile returns a non-dict (defensive). Never hardcodes a vendor; degrades to a
    no-op for Ollama / OpenAI-compatible lanes (FR-MIND-8).
    """
    if not provider_supports_prefix_cache(profile, posture=posture):
        return payload
    mark = getattr(profile, "mark_prefix_cache", None)
    if not callable(mark):
        return payload
    marked = mark(payload)
    return marked if isinstance(marked, dict) else payload
