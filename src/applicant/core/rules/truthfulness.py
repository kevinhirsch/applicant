"""Truthfulness & non-AI-looking post-filters (FR-RESUME-2, FR-RESUME-5, NFR-TRUTH-1).

Deterministic, always-on guards the core enforces on every generated/revised pass:

* **Em-dash normalization** — the spec forbids em-dashes (a notorious "AI tell").
  ``normalize_emdashes`` deterministically strips/normalizes them (and the related
  en-dash / double-hyphen forms) to plain ASCII so generated text never carries the
  tell. This is a *post-filter*: it runs after generation, every revision pass.
* **Banned-phrase detection + removal** — a curated (UI-extensible) list of
  LLM-cliché phrases, with a deterministic stripper so revisions never drift back
  toward generic AI prose.
* **Voice profile** — a cheap, deterministic style fingerprint extracted from the
  user's own resume corpus (avg sentence length, first-person ratio, vocabulary)
  used to *constrain* generation toward the candidate's own voice (FR-RESUME-5).
* **Fabrication detection** — compares generated skill/term claims against the
  candidate's TRUE attribute set / work history; anything unsupported is flagged
  (FR-RESUME-2, NFR-TRUTH-1). Pure helpers; the service raises on a violation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

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


def find_banned_phrases(text: str, extra: tuple[str, ...] = ()) -> list[str]:
    """Return the banned phrases present in ``text`` (case-insensitive), in order.

    ``extra`` lets the UI-editable banned-phrase list (FR-RESUME-5) supplement the
    built-in seed list without mutating the module-level constant.
    """
    if not text:
        return []
    low = text.lower()
    phrases = (*BANNED_PHRASES, *(p.lower() for p in extra if p.strip()))
    seen: list[str] = []
    for p in phrases:
        if p in low and p not in seen:
            seen.append(p)
    return seen


def has_banned_phrase(text: str, extra: tuple[str, ...] = ()) -> bool:
    """True if any banned phrase appears in ``text``."""
    return bool(find_banned_phrases(text, extra))


def strip_banned_phrases(text: str, extra: tuple[str, ...] = ()) -> str:
    """Deterministically remove banned phrases from ``text`` (FR-RESUME-5).

    Removes each banned phrase (case-insensitively, whole-phrase) and tidies the
    resulting whitespace/punctuation so revisions can never re-introduce a cliché.
    Idempotent.
    """
    if not text:
        return text
    out = text
    for phrase in (*BANNED_PHRASES, *(p.lower() for p in extra if p.strip())):
        out = re.sub(re.escape(phrase), "", out, flags=re.IGNORECASE)
    # Collapse the gaps a removal leaves behind (double spaces, orphaned commas).
    out = re.sub(r"\s+([,.;:])", r"\1", out)
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r"(^|\n)[ \t]*[,;:]\s*", r"\1", out)
    return out.strip(" \t")


def passes_post_filter(text: str, extra: tuple[str, ...] = ()) -> bool:
    """Convenience: True if ``text`` is em-dash-free and banned-phrase-free."""
    return not contains_emdash(text) and not has_banned_phrase(text, extra)


# === voice profile (FR-RESUME-5) ==========================================
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]*")
_SENTENCE_RE = re.compile(r"[.!?]+")
_FIRST_PERSON = frozenset({"i", "i'm", "i've", "i'd", "i'll", "my", "me", "mine", "we", "our"})


@dataclass(frozen=True)
class VoiceProfile:
    """A cheap, deterministic style fingerprint of the user's resume corpus.

    Extracted from the base resume + onboarding voice material so generation can be
    *constrained* to sound like the candidate (FR-RESUME-5), not generic AI prose.
    All metrics are corpus-derived, never invented, so the profile itself never
    introduces a truthfulness risk.
    """

    avg_sentence_words: float = 0.0
    first_person_ratio: float = 0.0
    vocabulary: frozenset[str] = field(default_factory=frozenset)
    sample_count: int = 0

    @property
    def is_empty(self) -> bool:
        return self.sample_count == 0

    def as_directive(self) -> str:
        """A one-line prompt directive summarizing the voice for the LLM."""
        if self.is_empty:
            return "Write in a warm, direct, first-person, active voice."
        person = "first-person" if self.first_person_ratio >= 0.02 else "professional"
        length = (
            "short, punchy sentences"
            if self.avg_sentence_words and self.avg_sentence_words < 16
            else "measured, substantive sentences"
        )
        return (
            f"Match the candidate's own voice: {person}, active voice, {length} "
            f"(~{round(self.avg_sentence_words)} words/sentence). Reuse their vocabulary."
        )


def extract_voice_profile(corpus: list[str]) -> VoiceProfile:
    """Build a :class:`VoiceProfile` from the user's resume/voice corpus.

    Deterministic and dependency-free so it runs offline (NFR-LOCAL-1).
    """
    texts = [t for t in corpus if t and t.strip()]
    if not texts:
        return VoiceProfile()
    joined = "\n".join(texts)
    words = [w.lower() for w in _WORD_RE.findall(joined)]
    if not words:
        return VoiceProfile(sample_count=len(texts))
    sentences = [s for s in _SENTENCE_RE.split(joined) if s.strip()]
    n_sentences = max(1, len(sentences))
    avg_words = len(words) / n_sentences
    fp = sum(1 for w in words if w in _FIRST_PERSON) / len(words)
    vocab = frozenset(w for w in words if len(w) >= 4)
    return VoiceProfile(
        avg_sentence_words=avg_words,
        first_person_ratio=fp,
        vocabulary=vocab,
        sample_count=len(texts),
    )


def voice_alignment(profile: VoiceProfile, text: str) -> float:
    """Fraction of ``text``'s significant words already in the corpus vocabulary.

    A coverage signal (0..1) for how "on-voice" a draft is, used to nudge (not gate)
    revisions back toward the candidate's own vocabulary (FR-RESUME-5).
    """
    if profile.is_empty or not text:
        return 1.0
    words = [w.lower() for w in _WORD_RE.findall(text) if len(w) >= 4]
    if not words:
        return 1.0
    hits = sum(1 for w in words if w in profile.vocabulary)
    return hits / len(words)


# === fabrication detection (FR-RESUME-2, NFR-TRUTH-1) =====================
#: Tokens that are not skill/qualification claims (keeps the check conservative).
_NON_CLAIM = frozenset(
    {
        "the", "and", "for", "with", "from", "that", "this", "have", "has", "was",
        "were", "are", "our", "their", "your", "you", "led", "built", "drove",
        "managed", "worked", "experience", "team", "teams", "role", "roles",
        "year", "years", "company", "i", "we", "my", "me", "a", "an", "of", "to",
        "in", "on", "at", "as", "by", "is", "it", "be", "or", "but",
    }
)


def candidate_claim_tokens(line: str) -> list[str]:
    """Tokens that look like skill/technology/qualification claims.

    Capitalized or ALL-CAPS multi-letter words (proper nouns / technology names),
    excluding obvious non-claim words. Used by the fabrication check.
    """
    tokens: list[str] = []
    for raw in re.split(r"[\s,.;:()\[\]{}/]+", line):
        word = raw.strip("'\"")
        if len(word) < 3:
            continue
        if word.lower() in _NON_CLAIM:
            continue
        if word[0].isupper() or word.isupper():
            tokens.append(word)
    return tokens


def unsupported_claims(true_text: str, generated: str) -> list[str]:
    """Return claim tokens in ``generated`` absent from the candidate's TRUE text.

    ``true_text`` is the candidate's real attribute set / work history / base
    source flattened to a string. Anything the generated material claims that is
    not traceable there is a fabrication candidate (FR-RESUME-2). Deterministic.
    """
    if not generated:
        return []
    source_low = true_text.lower()
    flagged: list[str] = []
    for line in generated.splitlines():
        for token in candidate_claim_tokens(line):
            if token.lower() not in source_low and token not in flagged:
                flagged.append(token)
    return flagged
