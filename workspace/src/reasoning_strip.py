"""Reasoning hygiene for the workspace chat path — strip model chain-of-thought.

Defense-in-depth twin of the engine's ``core/rules/reasoning_hygiene.py``:
the engine strips reasoning at its LLM-adapter seam, and this module applies
the SAME semantics at the workspace's own chat emit seam
(``routes/chat_routes.py``), so no chat path — engine-backed or native — can
surface a model's hidden chain-of-thought to the user.

Reasoning-tuned models (local Qwen-family checkpoints, OpenRouter-served
reasoning models, etc.) leak chain-of-thought in three wire shapes:

(a) inline tag blocks — ``<think>...</think>`` / ``<thinking>...`` /
    ``<reasoning>...`` — including malformed variants: an orphan closing tag
    whose opener was swallowed by the serving template, an opening tag that is
    never closed, and attribute-carrying spellings (``<think time="0.4">``);
(b) a separate ``reasoning`` / ``reasoning_content`` response field — handled
    at the route seam (deltas flagged ``thinking: true`` are dropped before
    they are emitted; this module only ever sees ``content`` text);
(c) an untagged "thinking process" preamble ("Here's a thinking process:
    1. ...", "Okay, the user has greeted me. ... Plan: ... Final answer: ...")
    when the serving template omits the tags entirely.

:func:`strip_reasoning` mirrors the engine function: CONSERVATIVE and
idempotent. Text with no reasoning markers passes through byte-identical; a
balanced ``<think>...</think>`` block is always removed; the ambiguous strips
(orphan closing tag, untagged preamble) only apply when a meaningful answer
survives; a strip never deletes the whole message — when nothing would
survive, the text minus bare tag markup is returned instead.

:class:`ReasoningStreamFilter` adapts those semantics to an SSE delta stream:
it never emits text that is (or may still become) reasoning, holds back
open/partial tag markup and reasoning-shaped preambles, and finishes with the
exact :func:`strip_reasoning` result at end-of-stream. Because a live stream
cannot un-print, the rare shape that reclassifies already-emitted text as
reasoning (an orphan closing tag arriving late) sets :attr:`diverged` so the
route can tell the client to replace the rendered text with the clean reply.
"""

from __future__ import annotations

import re

__all__ = ["strip_reasoning", "ReasoningStreamFilter"]

#: An ambiguous strip (orphan close / preamble heuristic) must leave at least
#: this many non-whitespace characters, or it is judged an overstrip and skipped.
_MIN_REMAINDER = 20

#: The reasoning-tag family (case-insensitive). Covers the common template
#: spellings; ``thought``/``thoughts`` and ``reflection``/``scratchpad`` appear
#: on some local fine-tunes.
_TAGS = (
    r"(?:think(?:ing)?|thoughts?|reason(?:ing)?|reflection|scratchpad|"
    r"internal[_-]?monologue|chain[_-]?of[_-]?thought|cot)"
)

#: Attribute-carrying spellings some backends emit (``<thinking time="0.42">``);
#: normalized to the bare tag before the structural passes so every regex below
#: only has to reason about ``<think>``-shaped tokens.
_ATTR_OPEN = re.compile(rf"<\s*(?P<tag>{_TAGS})\s+[^>]*>", re.IGNORECASE)
_ATTR_CLOSE = re.compile(rf"<\s*/\s*(?P<tag>{_TAGS})\s+[^>]*>", re.IGNORECASE)

#: A fully-formed reasoning block: ``<think> ... </think>`` (same tag on both
#: ends). Non-greedy so back-to-back blocks are removed independently.
_TAG_BLOCK = re.compile(
    rf"<\s*(?P<tag>{_TAGS})\s*>.*?<\s*/\s*(?P=tag)\s*>\s*",
    re.IGNORECASE | re.DOTALL,
)

#: Any bare reasoning tag token (open or close) — used for the conservative
#: "markup only" fallback and the final cleanup pass.
_TAG_MARKUP = re.compile(rf"<\s*/?\s*{_TAGS}\s*>", re.IGNORECASE)

#: Orphan CLOSING tag: chain-of-thought runs from the start of the message to a
#: ``</think>`` that was never opened (the template swallowed the opener —
#: the classic serving bug on reasoning checkpoints). Greedy ``.*`` so the LAST
#: orphan close bounds the reasoning.
_ORPHAN_CLOSE = re.compile(rf"\A.*<\s*/\s*{_TAGS}\s*>\s*", re.IGNORECASE | re.DOTALL)

#: Opening tag never closed: everything from the tag onward is chain-of-thought
#: (the model ran out of tokens mid-think, or trailed off thinking again).
_OPEN_UNCLOSED = re.compile(rf"<\s*{_TAGS}\s*>", re.IGNORECASE)

#: Untagged-preamble LEADS — the message must START with one of these for the
#: preamble heuristic to even be considered. Deliberately narrow: third-person
#: narration about "the user", an explicit thinking-process declaration, or a
#: self-directed planning opener. A normal reply addresses the user as "you"
#: and matches none of these.
_PREAMBLE_LEAD = re.compile(
    r"\A\s*(?:"
    r"here(?:'|’)?s\s+(?:a|my|the)\s+(?:thinking|thought)\s+process\b"
    r"|(?:my\s+|the\s+|a\s+)?(?:thinking|thought)\s+process\s*:"
    r"|okay,?\s+(?:so\s+)?the\s+user\b"
    r"|the\s+user\s+(?:has|is|was|wants|asked|asks|says?|said|greeted|typed|sent|wrote|writes)\b"
    r"|let\s+me\s+think\b"
    r"|let(?:'|’)?s\s+think\b"
    r"|first,?\s+i\s+(?:need|should|will|want)\b"
    r"|i\s+should\s+(?:start|first|introduce|respond|reply|figure|craft|think|greet)\b"
    r"|analyz(?:e|ing)\s+the\s+user\b"
    r")",
    re.IGNORECASE,
)

#: A clear FINAL-ANSWER boundary inside a thinking preamble. Only consulted
#: after ``_PREAMBLE_LEAD`` matched, so these may match mid-text. The LAST
#: match bounds the reasoning; everything after it is the answer.
_FINAL_BOUNDARY = re.compile(
    r"(?:"
    r"\*{0,2}(?:final\s+(?:polish|answer|response|reply|version|draft|output)"
    r"|actual\s+(?:answer|response|reply))\*{0,2}\s*[:\-–—]\s*"
    r"|\n\s*\*{0,2}(?:answer|response|reply)\*{0,2}\s*:\s*"
    r"|\n\s*(?:-{3,}|_{3,}|\*{3,})\s*\n"
    r")",
    re.IGNORECASE,
)

#: Explicit "here is my thinking process" declaration — the only lead strong
#: enough to also enable the paragraph-drop fallback when no boundary marker
#: exists (the declaration itself guarantees the head is reasoning).
_EXPLICIT_DECLARATION = re.compile(
    r"\A\s*(?:here(?:'|’)?s\s+(?:a|my|the)\s+)?(?:thinking|thought)\s+process\s*:",
    re.IGNORECASE,
)

#: A paragraph that still looks like reasoning scaffolding (numbered steps,
#: Plan/Drafting/Refinement headers, or another lead) — dropped while walking
#: forward from an explicit thinking-process declaration.
_REASONING_PARAGRAPH = re.compile(
    r"\A\s*(?:"
    r"\d+[.)]\s"
    r"|(?:plan|steps?|draft(?:ing)?|refin(?:e|ing|ement)|polish(?:ing)?"
    r"|analysis|analyz(?:e|ing)|approach|outline)\s*[:.\-]"
    r")",
    re.IGNORECASE,
)


def _normalize_tag_attrs(text: str) -> str:
    """Rewrite attribute-carrying family tags to their bare spelling."""
    text = _ATTR_OPEN.sub(lambda m: "<" + m.group("tag") + ">", text)
    return _ATTR_CLOSE.sub(lambda m: "</" + m.group("tag") + ">", text)


def _visible_len(text: str) -> int:
    """Non-whitespace character count — the 'is anything left?' measure."""
    return len(re.sub(r"\s+", "", text))


def _markup_only(text: str) -> str:
    """The conservative fallback: the text minus bare tag markup, trimmed."""
    return _TAG_MARKUP.sub("", text).strip()


def _strip_preamble(text: str) -> str:
    """Drop an untagged thinking-process preamble when a clear boundary exists.

    Only fires when the text STARTS with a recognized reasoning lead. Prefers an
    explicit final-answer boundary marker ("Final Polish:", a line-leading
    "Answer:", a ``---`` rule); for an explicit "thinking process" declaration
    it may instead drop leading reasoning-shaped paragraphs. Returns ``text``
    unchanged whenever the surviving answer would be too short — never guesses.
    """
    if not _PREAMBLE_LEAD.match(text):
        return text
    # Preferred: an explicit final-answer boundary; the LAST one wins.
    last = None
    for match in _FINAL_BOUNDARY.finditer(text):
        last = match
    if last is not None:
        remainder = text[last.end() :].strip()
        if _visible_len(remainder) >= _MIN_REMAINDER:
            return remainder
        return text
    # Fallback (explicit declaration only): drop leading reasoning paragraphs.
    if not _EXPLICIT_DECLARATION.match(text):
        return text
    paragraphs = re.split(r"\n\s*\n", text)
    idx = 1  # the first paragraph carried the declaration — always reasoning
    while idx < len(paragraphs) and (
        _REASONING_PARAGRAPH.match(paragraphs[idx])
        or _PREAMBLE_LEAD.match(paragraphs[idx])
    ):
        idx += 1
    remainder = "\n\n".join(paragraphs[idx:]).strip()
    if _visible_len(remainder) >= _MIN_REMAINDER:
        return remainder
    return text


def strip_reasoning(text: str) -> str:
    """Remove leaked chain-of-thought from ``text`` (conservative, idempotent).

    Handles balanced ``<think>``-family blocks, orphan closing tags, unclosed
    opening tags, and untagged thinking-process preambles with a clear
    final-answer boundary. Never deletes the whole message: when a strip would
    leave (almost) nothing, the text minus bare tag markup is returned instead.
    Text with no reasoning markers is returned byte-identical.
    """
    if not text:
        return text
    normalized = _normalize_tag_attrs(text)
    has_markup = bool(_TAG_MARKUP.search(normalized))
    if not has_markup and not _PREAMBLE_LEAD.match(normalized):
        return text  # fast path: nothing reasoning-shaped — byte-identical

    out = normalized
    if has_markup:
        # (1) Balanced blocks — unambiguous; always removed. If nothing at all
        # survives, fall back to the original minus markup (never empty a reply).
        stripped = _TAG_BLOCK.sub("", out)
        if _visible_len(stripped) == 0 and _visible_len(out) > 0:
            return _markup_only(normalized)
        out = stripped

        # (2) Orphan closing tag — reasoning from the start through the (last)
        # close. Ambiguous (the head might be the real answer with a stray
        # close), so only applied when a meaningful remainder survives.
        if _TAG_MARKUP.search(out):
            candidate = _ORPHAN_CLOSE.sub("", out, count=1)
            if candidate != out and _visible_len(candidate) >= _MIN_REMAINDER:
                out = candidate

        # (3) Unclosed opening tag — everything from the tag onward is
        # reasoning. When the tag is mid-text, the text before it is the real
        # answer (kept whatever its length); when the tag opens the message,
        # dropping would delete everything, so only the markup is removed.
        opener = _OPEN_UNCLOSED.search(out)
        if opener is not None:
            head = out[: opener.start()]
            if _visible_len(head) > 0:
                out = head

        # Any tag token that survived the passes above is stray markup.
        out = _TAG_MARKUP.sub("", out)

    # (4) Untagged thinking-process preamble (conservative, boundary-gated).
    out = _strip_preamble(out.strip()).strip()

    if not out and text.strip():
        return _markup_only(normalized)
    return out


#: Family words a trailing partial token must prefix-match to be withheld
#: (see :meth:`ReasoningStreamFilter._hold_partial_tag`).
_FAMILY_WORDS = (
    "think", "thinking", "thought", "thoughts", "reason", "reasoning",
    "reflection", "scratchpad", "internal_monologue", "internal-monologue",
    "chain_of_thought", "chain-of-thought", "cot",
)

#: A trailing ``<...`` fragment that could still become a family tag token:
#: optional close slash, a letter run, then anything attribute-shaped.
_PARTIAL_TAG = re.compile(r"<\s*/?\s*([A-Za-z_\-]*)([^>]*)\Z")


class ReasoningStreamFilter:
    """Incremental :func:`strip_reasoning` for an SSE delta stream.

    Feed each user-visible content delta through :meth:`feed` and emit only
    what it returns; call :meth:`flush` at end-of-message (or at an agent-round
    boundary) and emit its tail. Guarantees:

    * emitted text never contains tag markup or the inside of a tag block;
    * a reply that STARTS reasoning-shaped (untagged preamble) is withheld
      entirely until flush, which then applies the full end-of-message strip;
    * clean text streams through unchanged (modulo a short holdback while a
      trailing ``<th…`` fragment could still become a tag token);
    * :attr:`visible_text` is always the clean user-visible text so far — after
      flush it equals ``strip_reasoning(full_raw_text)`` exactly.

    A live stream cannot un-print: when a late marker reclassifies already-
    emitted text as reasoning (an orphan ``</think>`` whose opener was
    swallowed upstream), the filter freezes instead of retracting and sets
    :attr:`diverged` — the route then tells the client to replace the rendered
    text with :attr:`visible_text` so the completed bubble is clean.
    """

    #: Before anything is emitted, buffer until this many characters (or a
    #: newline / end-of-stream) so the untagged-preamble decision is made on a
    #: stable head instead of a two-word fragment.
    _LEAD_WINDOW = 96
    #: Longest trailing fragment worth withholding as a possible tag token.
    _MAX_TAG_TOKEN = 40

    def __init__(self) -> None:
        self._raw = ""
        self._emitted = ""
        self._stream_view = ""
        self._preamble_hold: bool | None = None  # None = undecided
        self._retracted = False
        self._diverged = False
        self._final: str | None = None

    # -- public surface ----------------------------------------------------

    @property
    def visible_text(self) -> str:
        """The clean user-visible text so far (final after :meth:`flush`)."""
        return self._final if self._final is not None else self._emitted

    @property
    def diverged(self) -> bool:
        """True when already-emitted text is not a prefix of the final clean
        text — the client should replace what it rendered with
        :attr:`visible_text`."""
        return self._diverged

    @property
    def is_empty(self) -> bool:
        """True while nothing has been fed — lets a segment-boundary caller
        skip a no-op flush/rebuild."""
        return not self._raw

    def feed(self, delta: str) -> str:
        """Ingest one content delta; return the safe text to emit now ("" ok)."""
        if self._final is not None or not delta:
            return ""
        self._raw += delta
        if self._preamble_hold is None:
            probe = self._raw.lstrip()
            if len(probe) < self._LEAD_WINDOW and "\n" not in probe:
                return ""  # still deciding — keep buffering the head
            self._preamble_hold = bool(_PREAMBLE_LEAD.match(probe))
        if self._preamble_hold:
            return ""  # reasoning-shaped head: everything waits for flush()
        return self._advance(self._stream_strip(self._raw))

    def flush(self, *, never_empty: bool = True) -> str:
        """End of message/segment: settle on the exact :func:`strip_reasoning`
        result and return whatever clean tail has not been emitted yet.

        ``never_empty=False`` is for MID-message segment boundaries (an agent
        round ending at a tool call): the engine's never-empty fallback exists
        to protect a whole reply from being blanked, but a segment that was
        pure reasoning (a balanced block, or one unclosed think from the top)
        should simply vanish — the surrounding tool activity is the visible
        content — instead of resurfacing de-tagged chain-of-thought.
        """
        if self._final is not None:
            return ""
        final = strip_reasoning(self._raw)
        if not never_empty and self._raw.strip():
            normalized = _normalize_tag_attrs(self._raw)
            residue = _TAG_BLOCK.sub("", normalized)
            opener = _OPEN_UNCLOSED.search(residue)
            if opener is not None and _visible_len(residue[: opener.start()]) == 0:
                residue = residue[: opener.start()]  # one unclosed think from the top
            residue = _TAG_MARKUP.sub("", residue)
            if _visible_len(residue) == 0:
                final = ""  # unambiguously reasoning-only — drop the segment
        self._final = final
        if final.startswith(self._emitted):
            tail = final[len(self._emitted):]
            self._emitted = final
            return tail
        self._diverged = True
        return ""

    # -- internals -----------------------------------------------------------

    def _advance(self, view: str) -> str:
        prev = self._stream_view
        self._stream_view = view
        if not self._retracted:
            if view.startswith(self._emitted):
                out = view[len(self._emitted):]
                self._emitted += out
                return out
            # A late marker reclassified emitted text as reasoning. We cannot
            # un-print mid-stream: freeze, flag the divergence, and emit only
            # NEW growth from here on (flush()/the route's replace event make
            # the completed bubble clean).
            self._retracted = True
            self._diverged = True
            return ""
        if view.startswith(prev):
            out = view[len(prev):]
            self._emitted += out
            return out
        return ""

    def _stream_strip(self, raw: str) -> str:
        """The streaming variant of :func:`strip_reasoning`: same passes, but
        an unclosed opener withholds (rather than drops) its tail — the block
        may still close — and the orphan-close cut skips the remainder gate
        (flush() re-decides with the conservative end-of-message rules)."""
        text = self._hold_partial_tag(_normalize_tag_attrs(raw))
        out = _TAG_BLOCK.sub("", text)
        if _TAG_MARKUP.search(out):
            out = _ORPHAN_CLOSE.sub("", out, count=1)
        opener = _OPEN_UNCLOSED.search(out)
        if opener is not None:
            out = out[: opener.start()]
        return _TAG_MARKUP.sub("", out)

    def _hold_partial_tag(self, text: str) -> str:
        """Withhold a trailing ``<think``-ish fragment until it either completes
        into a tag token or is disambiguated as ordinary text."""
        lt = text.rfind("<")
        if lt == -1 or ">" in text[lt:]:
            return text
        candidate = text[lt:]
        if len(candidate) > self._MAX_TAG_TOKEN:
            return text
        match = _PARTIAL_TAG.match(candidate)
        if not match:
            return text
        word = (match.group(1) or "").lower()
        if any(family.startswith(word) for family in _FAMILY_WORDS):
            return text[:lt]
        return text
