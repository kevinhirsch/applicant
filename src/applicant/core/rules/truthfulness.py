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
_EM_DASH = "—"  # — U+2014
_EN_DASH = "–"  # – U+2013
_HORIZONTAL_BAR = "―"  # ― U+2015
_MINUS_SIGN = "−"  # − U+2212
_TWO_EM_DASH = "⸺"  # ⸺ U+2E3A
_THREE_EM_DASH = "⸻"  # ⸻ U+2E3B
_FIGURE_DASH = "‒"  # ‒ U+2012
_FULLWIDTH_HYPHEN = "－"  # － U+FF0D

#: Em-dash-like code points normalized to ", " (parenthetical separators).
_EMDASH_LIKE = (_EM_DASH, _HORIZONTAL_BAR, _TWO_EM_DASH, _THREE_EM_DASH)
#: Dash-like code points normalized to a plain hyphen.
_HYPHEN_LIKE = (_EN_DASH, _MINUS_SIGN, _FIGURE_DASH, _FULLWIDTH_HYPHEN)

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
    # Spaced em/horizontal/two-em/three-em bars used as separators -> ", ".
    out = re.sub(rf"\s*[{''.join(_EMDASH_LIKE)}]\s*", ", ", out)
    # ASCII double(+)-hyphen used as an em-dash -> ", " (spacing not required).
    out = re.sub(r"\s*-{2,}\s*", ", ", out)
    # En-dash / minus / figure / fullwidth -> simple hyphen.
    for ch in _HYPHEN_LIKE:
        out = out.replace(ch, "-")
    return out


def contains_emdash(text: str) -> bool:
    """True if any em-dash-like code point or ``--`` run remains in ``text``."""
    if not text:
        return False
    if any(ch in text for ch in (*_EMDASH_LIKE, *_HYPHEN_LIKE)):
        return True
    return bool(re.search(r"-{2,}", text))


def _normalize_for_match(text: str) -> str:
    """Normalize text so banned-phrase matching is robust to LLM typography.

    LLMs emit curly apostrophes (``’`` U+2019) and uneven spacing that would let a
    cliché slip past an ASCII-only match (FR-RESUME-5). Fold curly quotes to ASCII
    and collapse internal whitespace before comparing.
    """
    out = text.replace("’", "'").replace("‘", "'")
    out = out.replace("“", '"').replace("”", '"')
    out = re.sub(r"\s+", " ", out)
    return out


def _banned_phrase_pattern(phrase: str) -> str:
    """Build a regex matching ``phrase`` tolerant of curly quotes + extra spaces.

    The seed phrases use ASCII apostrophes/spaces; generated text may use ``’`` and
    irregular whitespace, so each apostrophe matches either quote form and each run
    of whitespace matches one-or-more whitespace characters (FR-RESUME-5).
    """
    parts = []
    for ch in phrase:
        if ch in "'’‘":
            parts.append(r"['’‘]")
        elif ch.isspace():
            parts.append(r"\s+")
        else:
            parts.append(re.escape(ch))
    return "".join(parts)


def find_banned_phrases(text: str, extra: tuple[str, ...] = ()) -> list[str]:
    """Return the banned phrases present in ``text`` (case-insensitive), in order.

    ``extra`` lets the UI-editable banned-phrase list (FR-RESUME-5) supplement the
    built-in seed list without mutating the module-level constant.
    """
    if not text:
        return []
    low = _normalize_for_match(text.lower())
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
        out = re.sub(_banned_phrase_pattern(phrase), "", out, flags=re.IGNORECASE)
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
#
# The fabrication guard flags any whole token in generated material that is NOT in
# the candidate's true source. To catch a fabricated *skill / technology / proper
# noun / qualification* (e.g. "Kubernetes", "PhD", "Stanford") it must NOT also flag
# the ordinary English prose a cover letter is made of ("Dear", "spent", "would",
# "challenges"). Capitalization gating can't separate them — a lowercase fabricated
# skill ("kubernetes") must still be caught (NFR-TRUTH-1) — so the discriminator is a
# stopword list: common English / connective / scaffolding words are not claims;
# named technologies, organizations, degrees and the like are not stopwords and stay
# flagged. This is intentionally broad (free-prose cover letters, FR-RESUME-10).
_NON_CLAIM = frozenset(
    {
        # articles / determiners / quantifiers
        "the", "a", "an", "this", "that", "these", "those", "such", "some", "any",
        "all", "both", "each", "every", "few", "many", "most", "more", "much",
        "several", "no", "nor", "not", "other", "another", "same", "own", "only",
        "enough", "less", "least",
        # pronouns
        "i", "me", "my", "mine", "myself", "we", "us", "our", "ours", "ourselves",
        "you", "your", "yours", "yourself", "he", "him", "his", "she", "her", "hers",
        "it", "its", "they", "them", "their", "theirs", "who", "whom", "whose",
        "which", "what", "whatever", "whoever", "whichever", "someone", "anyone",
        "everyone", "something", "anything", "everything", "nothing",
        # interrogative / relative adverbs
        "how", "why", "when", "where", "here", "there", "whenever", "wherever",
        "whence", "hence", "thus",
        # prepositions / conjunctions / connectives
        "of", "to", "in", "on", "at", "as", "by", "for", "with", "from", "and", "or",
        "but", "yet", "so", "if", "then", "else", "than", "because", "since", "until",
        "till", "while", "whilst", "though", "although", "however", "whereas",
        "whether", "unless", "despite", "into", "onto", "upon", "over", "under",
        "above", "below", "between", "among", "amongst", "through", "throughout",
        "during", "before", "after", "about", "around", "along", "against", "toward",
        "towards", "within", "without", "off", "out", "up", "down", "again",
        "further", "once", "beyond", "across", "via", "per", "plus", "etc", "eg",
        "ie", "vs", "and/or",
        # be / have / do / modal + common auxiliary forms
        "is", "am", "are", "was", "were", "be", "been", "being", "have", "has", "had",
        "having", "do", "does", "did", "doing", "done", "will", "would", "shall",
        "should", "can", "could", "may", "might", "must", "ought",
        # common verbs (and their frequent inflections) — framing, not skill claims
        "get", "gets", "got", "getting", "gotten", "make", "makes", "made", "making",
        "take", "takes", "took", "taken", "taking", "go", "goes", "went", "gone",
        "going", "come", "comes", "came", "coming", "see", "sees", "saw", "seen",
        "seeing", "know", "knows", "knew", "known", "knowing", "think", "thinks",
        "thought", "thinking", "want", "wants", "wanted", "need", "needs", "needed",
        "help", "helps", "helped", "helping", "work", "works", "worked", "working",
        "build",
        "builds", "built", "building", "lead", "leads", "led", "leading", "ship",
        "ships", "shipped", "shipping", "run", "runs", "ran", "running", "give",
        "gives", "gave", "given", "giving", "find", "finds", "found", "finding",
        "spend", "spends", "spent", "spending", "bring", "brings", "brought", "hold",
        "holds", "held", "holding", "move", "moves", "moved", "moving", "draw",
        "draws", "drew", "drawn", "drawing", "drive", "drove", "drives", "driven",
        "driving", "keep", "keeps", "kept", "keeping", "put", "puts", "set", "sets",
        "show", "shows", "showed", "shown", "try", "tries", "tried", "trying", "ask",
        "asks", "asked", "turn", "turns", "turned", "start", "starts", "started",
        "starting", "begin", "begins", "began", "begun", "become", "becomes",
        "became", "becoming", "continue", "continues", "continued", "continuing",
        "grow", "grows", "grew", "grown", "growing", "teach", "teaches", "taught",
        "learn", "learns", "learned", "learning", "serve", "serves", "served",
        "serving", "reduce", "reduces", "reduced", "reducing", "design", "designs",
        "designed", "designing", "scale", "scales", "scaled", "scaling", "explore",
        "explores", "explored", "exploring", "mentor", "mentors", "mentored",
        "mentoring", "clear", "clears", "cleared", "clearing", "break", "breaks",
        "broke", "broken", "breaking", "align", "aligns", "aligned", "aligning",
        "welcome", "welcomes", "welcomed", "talk", "talks", "talked", "tend", "tends",
        "tended", "require", "requires", "required", "allow", "allows", "allowed",
        "enable", "enables", "enabled", "deliver", "delivers", "delivered",
        "managed", "manage", "manages", "use", "used", "using", "uses",
        "wrote", "write", "writes", "writing", "written", "apply", "applies",
        "applied", "applying", "improve", "improves", "improved", "improving",
        # adjectives / adverbs — framing, not skill claims
        "good", "great", "best", "better", "strong", "solid", "deep", "deeper",
        "wide", "broad", "recent", "recently", "last", "first", "second", "third",
        "new", "old", "real", "very", "well", "just", "also", "even", "quite",
        "really", "genuinely", "mostly", "roughly", "clearly", "simply", "especially",
        "particularly", "highly", "truly", "fully", "currently", "lately", "now",
        "soon", "ago", "today", "complex", "simple", "practical", "reliable",
        "rewarding", "right", "wrong", "able", "key", "core", "major", "minor",
        "significant", "important", "large", "small", "big", "high", "low", "fast",
        "slow", "quick", "quickly", "careful", "carefully", "effective", "efficient",
        "successful", "proven", "various", "including", "include", "includes",
        "expert", "experienced", "skilled", "proficient", "professional", "hands-on",
        # generic professional / prose nouns — not specific fabricable claims
        "experience", "team", "teams", "role", "roles", "year", "years", "company",
        "companies", "time", "times", "way", "ways", "thing", "things", "people",
        "person", "project", "projects", "challenge", "challenges", "path", "paths",
        "effort", "efforts", "load", "loads", "intersection", "product", "products",
        "user", "users", "trust", "confidence", "care", "lot", "lots", "system",
        "systems", "platform", "platforms", "service", "services", "application",
        "applications", "deployment", "deployments", "migration", "migrations",
        "infrastructure", "architecture", "pipeline", "pipelines", "solution",
        "solutions", "process", "processes", "approach", "approaches", "result",
        "results", "impact", "value", "goal", "goals", "focus", "opportunity",
        "opportunities", "position", "positions", "candidate", "requirement",
        "requirements", "skill", "skills", "qualification", "qualifications",
        "background", "history", "summary", "objective", "responsibility",
        "responsibilities", "environment", "environments", "growth", "leadership",
        "collaboration", "communication", "ownership", "delivery", "quality",
        "reliability", "performance", "engineer", "engineers", "engineering",
        "developer", "developers", "dev", "manager", "management", "member",
        "members", "contributor", "contribution", "contributions", "chance",
        # salutation / cover-letter scaffolding
        "dear", "hi", "hello", "hey", "hiring", "sincerely", "regards", "warmly",
        "thanks", "thank", "name", "signature", "letter", "cover", "applicant",
        "resume", "résumé", "attached", "enclosed", "organization", "organisation",
        "firm",
        # number words (spelled-out quantities are too noisy to treat as claims)
        "zero", "one", "ones", "two", "three", "four", "five", "six", "seven",
        "eight", "nine", "ten", "eleven", "twelve", "thirteen", "fourteen",
        "fifteen", "sixteen", "seventeen", "eighteen", "nineteen", "twenty",
        "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety",
        "hundred", "thousand", "million", "millions", "billion", "percent", "dozen",
        "dozens", "half", "quarter",
    }
)


def candidate_claim_tokens(line: str) -> list[str]:
    """Tokens that look like skill/technology/qualification claims.

    Multi-letter words (skills / technology names / qualifications), excluding
    obvious non-claim filler words. Capitalization is NOT required: lowercase
    skill claims like "kubernetes" must still be checked (FR-RESUME-2,
    NFR-TRUTH-1).
    """
    tokens: list[str] = []
    for raw in re.split(r"[\s,.;:()\[\]{}/]+", line):
        word = raw.strip("'\"")
        if len(word) < 3:
            continue
        if word.lower() in _NON_CLAIM:
            continue
        tokens.append(word)
    return tokens


def _source_token_set(true_text: str) -> frozenset[str]:
    """Whole-token (lowercased) set of the candidate's TRUE source.

    Membership is checked per whole token so "Java" never falsely "supports" a
    "JavaScript" claim (substring containment was the bug — NFR-TRUTH-1).
    """
    return frozenset(
        t.strip("'\"").lower()
        for t in re.split(r"[\s,.;:()\[\]{}/]+", true_text)
        if t.strip("'\"")
    )


def unsupported_claims(true_text: str, generated: str) -> list[str]:
    """Return claim tokens in ``generated`` absent from the candidate's TRUE text.

    ``true_text`` is the candidate's real attribute set / work history / base
    source flattened to a string. Anything the generated material claims that is
    not traceable there (by WHOLE-TOKEN membership, not substring) is a fabrication
    candidate (FR-RESUME-2). Deterministic.
    """
    if not generated:
        return []
    source_tokens = _source_token_set(true_text)
    flagged: list[str] = []
    for line in generated.splitlines():
        for token in candidate_claim_tokens(line):
            if token.lower() not in source_tokens and token not in flagged:
                flagged.append(token)
    return flagged
