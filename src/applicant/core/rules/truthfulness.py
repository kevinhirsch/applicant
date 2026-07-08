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
* **Graded fabrication** — :func:`grade_unsupported_claims` maps flagged-token
  count to CLEAN / REVIEW / VIOLATION so a single ambiguous token queues for
  human review rather than hard-failing (FR-HARVEST-TRUTHTIER).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

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


# --- numeric grounding (FR-RESUME-2): match figures by VALUE, not spelling --------
# A generated figure legitimately reformats a source figure ("40k" -> "40,000",
# "$30M" -> "$30,000,000", "27%" -> "27"); flagging that as fabrication blocked real
# cover letters / screening answers. We compare numeric VALUES so reformatting passes
# while a genuinely invented quantity (a 38% source figure surfacing as 80%) is still
# caught. Numbers are handled separately from word claims because the token split
# shreds "40,000" into "40"/"000" before a per-token check could ever see it.
_NUM_TOKEN_RE = re.compile(
    r"\$?\d[\d,]*(?:\.\d+)?(?:\s?(?:k|m|b|thousand|million|billion)(?![a-z]))?",
    re.IGNORECASE,
)
_NUM_MULTIPLIER = {
    "k": 1e3, "thousand": 1e3, "m": 1e6, "million": 1e6, "b": 1e9, "billion": 1e9,
}


def _number_value(token: str) -> float | None:
    """Canonical numeric value of a figure token (``$``/``,``/``%`` stripped, k/M/B applied)."""
    s = token.strip().lower().lstrip("$").rstrip("%").strip()
    mult = 1.0
    for suffix, factor in _NUM_MULTIPLIER.items():
        if s.endswith(suffix):
            s = s[: -len(suffix)].strip()
            mult = factor
            break
    s = s.replace(",", "")
    if not s:
        return None
    try:
        return float(s) * mult
    except ValueError:
        return None


def _numeric_values(text: str) -> set[float]:
    """Set of canonical numeric values appearing in ``text`` (for value-matching)."""
    vals: set[float] = set()
    for m in _NUM_TOKEN_RE.finditer(text):
        v = _number_value(m.group(0))
        if v is not None:
            vals.add(v)
    return vals


def _unsupported_numbers(generated: str, source_values: set[float]) -> list[str]:
    """Figure tokens in ``generated`` whose VALUE is absent from the source (FR-RESUME-2)."""
    flagged: list[str] = []
    for m in _NUM_TOKEN_RE.finditer(generated):
        token = m.group(0).strip()
        value = _number_value(token)
        if value is None:
            continue
        if value not in source_values and token not in flagged:
            flagged.append(token)
    return flagged


def unsupported_claims(true_text: str, generated: str) -> list[str]:
    """Return claim tokens in ``generated`` absent from the candidate's TRUE text.

    ``true_text`` is the candidate's real attribute set / work history / base
    source flattened to a string. Anything the generated material claims that is
    not traceable there (by WHOLE-TOKEN membership, not substring) is a fabrication
    candidate (FR-RESUME-2). Figures are value-matched (``40k`` ≡ ``40,000``) rather
    than spelling-matched. Deterministic.
    """
    if not generated:
        return []
    source_tokens = _source_token_set(true_text)
    flagged: list[str] = _unsupported_numbers(generated, _numeric_values(true_text))
    for line in generated.splitlines():
        for token in candidate_claim_tokens(line):
            if any(c.isdigit() for c in token):
                continue  # figures are value-matched above, not spelling-matched
            if token.lower() not in source_tokens and token not in flagged:
                flagged.append(token)
    return flagged


#: Quote/apostrophe code points stripped from token edges (straight + curly).
_QUOTE_CHARS = "'\"\u2018\u2019\u201c\u201d"

#: Word split for free-prose checking: whitespace/punctuation AND hyphens +
#: markdown markers (*`~_|<>#), shared by the prose checker and the provenance
#: attribution so the two can never tokenize differently.
_PROSE_WORD_SPLIT_RE = re.compile(r"[\s,.;:()\[\]{}/*`~_|<>#\-]+")

#: Contraction split ("I've"/"it's" never read as proper nouns).
_CONTRACTION_SPLIT_RE = re.compile(r"['\u2019\u2018]")


def _prose_source_tokens(true_text: str) -> frozenset[str]:
    """Lenient source-token set for free-prose checking.

    Like :func:`_source_token_set` but also splits on hyphens (so "LLM-powered"
    contributes "llm") and adds a crude singular for plural tokens (so a "LLMs"
    mention is supported by an "LLM" in the source). This looseness is acceptable
    for the prose check, which only ever inspects entity-shaped tokens.
    """
    toks: set[str] = set()
    for raw in re.split(r"[\s,.;:()\[\]{}/\-]+", true_text):
        t = raw.strip(_QUOTE_CHARS).lower()
        if not t:
            continue
        toks.add(t)
        if len(t) > 3 and t.endswith("s"):
            toks.add(t[:-1])
    return frozenset(toks)


def _is_entity_shaped(word: str, *, sentence_initial: bool) -> bool:
    """True if ``word`` looks like a named claim (skill / org / acronym / number).

    Free prose is full of ordinary lowercase words that are not claims; the things
    a cover letter could *fabricate* are named entities — proper nouns (Stanford,
    Kubernetes), acronyms (AWS, SQL, MBA), mixed-case tech (FastAPI, PostgreSQL),
    and numbers/dates (2015, 70%). A leading-capital word is only treated as a
    proper noun when it is NOT sentence-initial, since sentence-initial capitals are
    just grammar ("Lately, …", "Based on …").
    """
    if any(c.isdigit() for c in word):
        return True
    letters = [c for c in word if c.isalpha()]
    if len(letters) >= 2 and all(c.isupper() for c in letters):
        return True  # ALL-CAPS acronym
    if any(c.isupper() for c in word[1:]):
        return True  # internal/camel caps (FastAPI, PostgreSQL)
    if not sentence_initial and word[:1].isupper() and any(c.islower() for c in word):
        return True  # mid-sentence proper noun
    return False


def unsupported_prose_claims(true_text: str, generated: str) -> list[str]:
    """Fabrication check tuned for FREE PROSE (cover letters, essays; FR-RESUME-10).

    A cover letter legitimately uses an open-ended vocabulary of ordinary words
    that will never all appear in the terse résumé source, so the strict per-token
    :func:`unsupported_claims` (right for résumé bullets) rejects every natural
    letter. Here we only flag *entity-shaped* tokens (named skills / orgs /
    acronyms / numbers, see :func:`_is_entity_shaped`) that are absent from the
    source — so an invented "Stanford" / "AWS" / "PhD" / "2015" is still caught,
    while narrative prose passes. Contractions are split on the apostrophe so
    "I've"/"it's" never read as proper nouns. Deterministic.
    """
    if not generated:
        return []
    source = _prose_source_tokens(true_text)
    # Figures are matched by VALUE (40k ≡ 40,000) up front; the word loop then skips
    # any digit-bearing token so a reformatted number is never a false fabrication.
    flagged: list[str] = _unsupported_numbers(generated, _numeric_values(true_text))
    # Split into sentences so we can tell a sentence-initial capital (grammar) from
    # a mid-sentence proper noun (a real entity claim).
    for sentence in re.split(r"(?<=[.!?])\s+", generated):
        first = True
        # Split on whitespace/punctuation AND hyphens + markdown markers (*`~_|<>#),
        # so "LLM-powered" matches the hyphen-split source and "**Subject**" sheds its
        # bold markers instead of reading as a fabricated proper noun.
        for raw in _PROSE_WORD_SPLIT_RE.split(sentence):
            for piece in _CONTRACTION_SPLIT_RE.split(raw):  # split contractions
                word = piece.strip(_QUOTE_CHARS)
                if not word:
                    continue
                sentence_initial = first
                first = False
                if len(word) < 2 or word.lower() in _NON_CLAIM:
                    continue
                if any(c.isdigit() for c in word):
                    continue  # figures handled by value-matching above
                low = word.lower()
                if low in source or (low.endswith("s") and low[:-1] in source):
                    continue
                if _is_entity_shaped(word, sentence_initial=sentence_initial):
                    if word not in flagged:
                        flagged.append(word)
    return flagged


# === graded fabrication outcome (FR-HARVEST-TRUTHTIER) ===================


class FabricationGrade(str, Enum):
    """Graded severity of an unsupported-claims check (FR-HARVEST-TRUTHTIER).

    CLEAN     — zero unsupported tokens; output can proceed as-is.
    REVIEW    — one ambiguous token; surface to human reviewer before publishing.
    VIOLATION — two or more clear fabrications; caller must raise / block.
    """

    CLEAN = "clean"
    REVIEW = "review"
    VIOLATION = "violation"


def grade_unsupported_claims(
    true_text: str,
    generated: str,
    *,
    prose: bool = False,
    violation_threshold: int = 2,
) -> tuple[FabricationGrade, list[str]]:
    """Graded wrapper around the fabrication checkers (FR-HARVEST-TRUTHTIER).

    Runs :func:`unsupported_prose_claims` (``prose=True``) or
    :func:`unsupported_claims` (default) and maps flagged-token count to a tier:

    * ``CLEAN``     — 0 unsupported tokens.
    * ``REVIEW``    — 1 … ``violation_threshold``-1 tokens; ambiguous single-entity
                      case: queue for human review rather than hard-failing.
    * ``VIOLATION`` — ≥ ``violation_threshold`` tokens (default 2); caller should
                      raise / block, matching the existing hard-fail behaviour.

    Returns ``(grade, flagged)`` so callers can both branch on severity and
    log the specific tokens. Deterministic; no I/O.
    """
    checker = unsupported_prose_claims if prose else unsupported_claims
    flagged = checker(true_text, generated)
    n = len(flagged)
    if n == 0:
        grade = FabricationGrade.CLEAN
    elif n < violation_threshold:
        grade = FabricationGrade.REVIEW
    else:
        grade = FabricationGrade.VIOLATION
    return grade, flagged


# === truth policy (P1-13, owner directive) ================================
#
# The guard historically HARD-BLOCKED generation on any unsupported entity token.
# The owner's policy is looser and, critically, safe because a human approves every
# send (review-before-submit + the final-say invariant): the model may freely
# rewrite/restructure prose; it must not invent *facts* (employers, titles,
# credentials, technologies, dates, numbers) — but invented facts are SURFACED as
# suggestions to confirm, not silently blocked or silently kept.
#
#   BALANCED (default) — rewriting is free; flagged facts are surfaced (never raise).
#                        Nothing ships unreviewed, so "surface not block" is safe.
#   STRICT             — the historical behaviour: any flagged fact hard-fails.


class TruthPolicy(str, Enum):
    """How the fabrication guard acts on flagged (unsupported) claims."""

    BALANCED = "balanced"
    STRICT = "strict"


DEFAULT_TRUTH_POLICY = TruthPolicy.BALANCED


def coerce_truth_policy(value: object) -> TruthPolicy:
    """Best-effort parse of a config value into a TruthPolicy (default BALANCED).

    Accepts a TruthPolicy, its string value, or anything else (→ default). Never
    raises — a bad setting degrades to the safe-but-permissive default rather than
    crashing generation.
    """
    if isinstance(value, TruthPolicy):
        return value
    try:
        return TruthPolicy(str(value).strip().lower())
    except Exception:
        return DEFAULT_TRUTH_POLICY


def policy_blocks(flagged: list[str], policy: TruthPolicy) -> bool:
    """Whether flagged facts should HARD-BLOCK generation under ``policy``.

    STRICT blocks on any flagged fact; BALANCED never blocks (the caller surfaces
    the flags as suggestions instead). Pure; deterministic; no I/O.
    """
    if not flagged:
        return False
    return policy is TruthPolicy.STRICT


# === visible provenance (H4) ==============================================
#
# The fabrication guard already decides WHETHER a generated fact traces to the
# candidate's real history; H4 makes that decision LEGIBLE at review time — for
# each line of a generated document, WHICH ground-truth source (which profile
# attribute, the base résumé, the job posting being addressed) supports each
# fact-class token, and which tokens trace to nothing (unsourced ⇒ flagged, not
# hidden). Pure, deterministic re-use of the same tokenizers/matchers the guard
# itself runs, so the provenance view can never disagree with the guard.


@dataclass(frozen=True)
class FactTrace:
    """One fact-class token on a generated line and the sources that support it.

    ``sources`` holds the labels of the ground-truth components (a profile
    attribute, the base résumé, the posting context) containing the token; empty
    means the token traces to NOTHING the candidate provided — unsourced, to be
    flagged in review (H4), never hidden.
    """

    token: str
    sources: tuple[str, ...] = ()

    @property
    def unsourced(self) -> bool:
        return not self.sources


@dataclass(frozen=True)
class LineProvenance:
    """Provenance of one generated line: its fact-class tokens, each traced."""

    line: str
    facts: tuple[FactTrace, ...] = ()


def _line_words(line: str, *, prose: bool) -> frozenset[str]:
    """Every word token on ``line``, split exactly as the matching checker splits.

    Attribution only — no claim-shape filtering happens here (that already ran
    document-wide), so a token the guard extracted is found on its line even
    when the line, read in isolation, would misclassify it.
    """
    if not prose:
        return frozenset(candidate_claim_tokens(line))
    words: set[str] = set()
    for raw in _PROSE_WORD_SPLIT_RE.split(line):
        for piece in _CONTRACTION_SPLIT_RE.split(raw):
            word = piece.strip(_QUOTE_CHARS)
            if word:
                words.add(word)
    return frozenset(words)


def _claim_tokens_in_line(line: str, doc_tokens: list[str], *, prose: bool) -> list[str]:
    """The document-extracted claim tokens that occur on ``line``.

    ``doc_tokens`` is the checker's SINGLE pass over the whole document (empty
    source ⇒ every checkable token), so extraction shares the guard's sentence
    state; this helper only ATTRIBUTES each extracted token to the lines it
    appears on. Re-running the extractor per isolated line (the old approach)
    reset sentence-initial state at every newline, so a proper noun that a
    wrapped sentence pushed to the start of a line ("I worked at\\nStanford.")
    read as sentence-initial grammar and vanished from the per-line view even
    while the document-level guard flagged it.
    """
    words = _line_words(line, prose=prose)
    out: list[str] = []
    for token in doc_tokens:
        if any(c.isdigit() for c in token):
            # Figures are regex-extracted spans ("40,000"), which a word split
            # would shred — locate them on the line with the same regex.
            if any(m.group(0).strip() == token for m in _NUM_TOKEN_RE.finditer(line)):
                out.append(token)
        elif token in words:
            out.append(token)
    return out


def _sentence_initial_sourced_tokens(
    generated: str, sources: list[tuple[str, str]], skip: set[str]
) -> list[str]:
    """Sentence-initial entity-shaped tokens that trace to a source (prose only).

    The prose guard deliberately reads a sentence-initial capital as grammar,
    never a claim — right for FLAGGING (an ordinary sentence start must not
    read as a fabrication), but the provenance view also wants to SHOW support
    for a real detail the writer happened to lead a sentence with ("Python
    powered the migration."). This walks sentences exactly as the checker does,
    keeps only the first word when it would be entity-shaped mid-sentence, and
    returns it only when a source actually supports it — an unsupported
    sentence starter stays grammar (excluded), so the unsourced set still
    matches the guard's flag set exactly.
    """
    out: list[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+", generated):
        first_word = ""
        for raw in _PROSE_WORD_SPLIT_RE.split(sentence):
            for piece in _CONTRACTION_SPLIT_RE.split(raw):
                word = piece.strip(_QUOTE_CHARS)
                if word:
                    first_word = word
                    break
            if first_word:
                break
        word = first_word
        if (
            len(word) < 2
            or word.lower() in _NON_CLAIM
            or any(c.isdigit() for c in word)
            or word in skip
            or word in out
            or not _is_entity_shaped(word, sentence_initial=False)
        ):
            continue
        if any(_component_supports(text, word, prose=True) for _, text in sources):
            out.append(word)
    return out


def _component_supports(text: str, token: str, *, prose: bool) -> bool:
    """Whole-token (or numeric-value) support of ``token`` by one source text."""
    if any(c.isdigit() for c in token):
        value = _number_value(token)
        return value is not None and value in _numeric_values(text)
    low = token.lower()
    if prose:
        toks = _prose_source_tokens(text)
        return low in toks or (low.endswith("s") and low[:-1] in toks)
    return low in _source_token_set(text)


def trace_line_provenance(
    sources: list[tuple[str, str]], generated: str, *, prose: bool = False
) -> tuple[LineProvenance, ...]:
    """Trace each line of ``generated`` back to labelled ground-truth sources (H4).

    ``sources`` is ``[(label, text), ...]`` — the candidate's real history broken
    into its named components (each profile attribute, the base résumé, the
    posting context). For every non-empty line the fact-class tokens are
    extracted with the same tokenizer the fabrication guard uses (``prose``
    selects the cover-letter/essay entity-shaped check), and each token is
    matched against each component: the result names WHICH source supports it,
    or leaves ``sources`` empty when nothing does (unsourced ⇒ the review UI
    flags it, mirroring the guard's own flag set). Deterministic; no I/O.
    """
    checker = unsupported_prose_claims if prose else unsupported_claims
    combined = "\n".join(text for _, text in sources)
    # The guard's own document-level verdict: tokens tracing to nothing. Using
    # the document-level set (not a per-line re-check) keeps this view exactly
    # consistent with ``flagged_facts_for_document`` / ``assert_no_fabrication``.
    unsourced = set(checker(combined, generated))
    # The full claim-token list, extracted ONCE over the whole document (empty
    # source ⇒ every checkable token is "unsupported") so sentence state spans
    # newlines exactly as it does in the guard's own pass; each line below only
    # attributes these tokens, never re-extracts.
    doc_tokens = checker("", generated)
    if prose:
        # Sentence-initial sourced details ("Python powered the migration."):
        # shown WITH their source, never flagged — see the helper's docstring.
        doc_tokens = doc_tokens + _sentence_initial_sourced_tokens(
            generated, sources, skip=set(doc_tokens) | unsourced
        )
    out: list[LineProvenance] = []
    for line in generated.splitlines():
        if not line.strip():
            continue
        facts: list[FactTrace] = []
        seen: set[str] = set()
        for token in _claim_tokens_in_line(line, doc_tokens, prose=prose):
            if token in seen:
                continue
            seen.add(token)
            if token in unsourced:
                facts.append(FactTrace(token=token))
                continue
            supporting = tuple(
                label
                for label, text in sources
                if _component_supports(text, token, prose=prose)
            )
            facts.append(FactTrace(token=token, sources=supporting))
        out.append(LineProvenance(line=line, facts=tuple(facts)))
    return tuple(out)
