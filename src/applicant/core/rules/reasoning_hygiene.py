"""Reasoning hygiene — strip model chain-of-thought from user-facing text.

Pure functions, no IO (core/rules). Reasoning-tuned models (local Qwen-family
checkpoints, OpenRouter-served reasoning models, etc.) leak their hidden
chain-of-thought into the visible reply in three wire shapes:

(a) inline tag blocks — ``<think>...</think>`` / ``<thinking>...`` /
    ``<reasoning>...`` — including the malformed variants a misconfigured chat
    template produces: an orphan closing tag with no opener (the opener was
    swallowed by the template) or an opening tag that is never closed;
(b) a separate ``reasoning`` / ``reasoning_content`` response field — handled
    at the adapter seam (the field is simply never read into user-facing text;
    this module only ever sees the ``content`` string);
(c) an untagged "thinking process" preamble ("The user has greeted me. ...
    Plan: ... Drafting: ... Final Polish: <answer>", "Here's a thinking
    process: 1. ...") when the serving template omits the tags entirely.

:func:`strip_reasoning` is CONSERVATIVE and idempotent on the shapes above:

* Text with no reasoning markers passes through byte-identical (JSON, prose,
  tool-call argument strings are untouched).
* A *balanced* ``<think>...</think>`` block is unambiguous chain-of-thought and
  is always removed — even when the surviving answer is short ("Hi!"), because
  keeping leaked reasoning is strictly worse than a short reply.
* The *ambiguous* strips (orphan closing tag, untagged preamble) only apply
  when a meaningful answer (>= ``_MIN_REMAINDER`` non-whitespace chars)
  survives; otherwise only the bare tag markup is removed — the whole message
  is never deleted, and a strip never leaves (almost) nothing behind.
"""

from __future__ import annotations

import re

__all__ = ["strip_reasoning"]

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
#: the classic DeepSeek/Qwen serving bug). Greedy ``.*`` so the LAST orphan
#: close bounds the reasoning.
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
    has_markup = bool(_TAG_MARKUP.search(text))
    if not has_markup and not _PREAMBLE_LEAD.match(text):
        return text  # fast path: nothing reasoning-shaped — byte-identical

    out = text
    if has_markup:
        # (1) Balanced blocks — unambiguous; always removed. If nothing at all
        # survives, fall back to the original minus markup (never empty a reply).
        stripped = _TAG_BLOCK.sub("", out)
        if _visible_len(stripped) == 0 and _visible_len(out) > 0:
            return _markup_only(text)
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
        return _markup_only(text)
    return out
