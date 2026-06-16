"""Truthfulness & non-AI-looking post-filters (FR-RESUME-2, FR-RESUME-5, NFR-TRUTH-1).

Two deterministic concerns live here:

* **Em-dash normalization** — the spec forbids em-dashes (a notorious "AI tell").
  ``normalize_emdashes`` deterministically strips/normalizes them (and the related
  en-dash / double-hyphen forms) to plain ASCII so generated text never carries the
  tell. This is a *post-filter*: it runs after generation, every revision pass.
* **Banned-phrase detection** — a curated list of LLM-cliché phrases. The deeper
  voice-matching / fabrication-detection lands in Phase 3; this module provides the
  deterministic, always-on guard the core can rely on today.
"""

from __future__ import annotations

import re

# Unicode dash characters that read as "em-dash-like" and must not survive.
_EM_DASH = "—"  # —
_EN_DASH = "–"  # –
_HORIZONTAL_BAR = "―"  # ―
_MINUS_SIGN = "−"  # −

#: Phrases strongly associated with AI-generated prose. Lowercased for matching.
BANNED_PHRASES: tuple[str, ...] = (
    "delve into",
    "in today's fast-paced world",
    "it's important to note",
    "a testament to",
    "navigating the complexities",
    "unlock your potential",
    "in the realm of",
    "tapestry of",
    "at the end of the day",
    "leverage synergies",
    "i am excited to",
    "passionate about leveraging",
    "results-driven professional with a proven track record",
)


def normalize_emdashes(text: str) -> str:
    """Replace em-dash-like characters with plain ASCII (deterministic post-filter).

    * ``—`` / ``―`` / ``--`` between spaces -> ``", "`` style hyphen separator.
    * Standalone en-dash / minus -> ``-``.

    The result contains no em-dash code points. Idempotent.
    """
    if not text:
        return text
    out = text
    # Spaced em/horizontal bars used as parenthetical separators -> ", ".
    out = re.sub(rf"\s*[{_EM_DASH}{_HORIZONTAL_BAR}]\s*", ", ", out)
    # ASCII double-hyphen used as an em-dash -> ", ".
    out = re.sub(r"\s+--\s+", ", ", out)
    # En-dash / minus sign -> simple hyphen.
    out = out.replace(_EN_DASH, "-").replace(_MINUS_SIGN, "-")
    return out


def contains_emdash(text: str) -> bool:
    """True if any em-dash-like code point or spaced ``--`` remains in ``text``."""
    if not text:
        return False
    if any(ch in text for ch in (_EM_DASH, _EN_DASH, _HORIZONTAL_BAR, _MINUS_SIGN)):
        return True
    return bool(re.search(r"\s+--\s+", text))


def find_banned_phrases(text: str) -> list[str]:
    """Return the banned phrases present in ``text`` (case-insensitive), in order."""
    if not text:
        return []
    low = text.lower()
    return [p for p in BANNED_PHRASES if p in low]


def has_banned_phrase(text: str) -> bool:
    """True if any banned phrase appears in ``text``."""
    return bool(find_banned_phrases(text))


def passes_post_filter(text: str) -> bool:
    """Convenience: True if ``text`` is em-dash-free and banned-phrase-free."""
    return not contains_emdash(text) and not has_banned_phrase(text)
