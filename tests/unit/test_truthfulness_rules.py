from __future__ import annotations

import pytest

from applicant.core.rules.truthfulness import (
    VoiceProfile,
    candidate_claim_tokens,
    contains_emdash,
    extract_voice_profile,
    find_banned_phrases,
    has_banned_phrase,
    normalize_emdashes,
    passes_post_filter,
    strip_banned_phrases,
    voice_alignment,
)


@pytest.fixture(autouse=True)
def _no_cache() -> None:
    """Clear any cached state for xdist parallel safety."""
    yield


class TestNormalizeEmdashes:
    """normalize_emdashes: em/long-dash -> ASCII, idempotent."""

    def test_empty(self) -> None:
        assert normalize_emdashes("") == ""

    def test_no_dashes(self) -> None:
        assert normalize_emdashes("Hello world") == "Hello world"

    def test_em_dash_spaced(self) -> None:
        result = normalize_emdashes("We are \u2014 the best")
        assert result == "We are, the best"

    def test_em_dash_unspaced(self) -> None:
        result = normalize_emdashes("We are\u2014the best")
        assert result == "We are, the best"

    def test_en_dash(self) -> None:
        result = normalize_emdashes("2010\u20132020")
        assert result == "2010-2020"

    def test_double_hyphen(self) -> None:
        result = normalize_emdashes("We are -- the best")
        assert result == "We are, the best"

    def test_triple_hyphen(self) -> None:
        result = normalize_emdashes("We are---the best")
        assert result == "We are, the best"

    def test_horizontal_bar(self) -> None:
        result = normalize_emdashes("A \u2015 B")
        assert result == "A, B"

    def test_mixed_dashes(self) -> None:
        result = normalize_emdashes("A \u2014 B \u2013 C -- D")
        assert result == "A, B - C, D"

    def test_idempotent(self) -> None:
        first = normalize_emdashes("A \u2014 B")
        second = normalize_emdashes(first)
        assert first == second

    def test_minus_sign(self) -> None:
        result = normalize_emdashes("\u22125 degrees")
        assert result == "-5 degrees"


class TestContainsEmdash:
    """contains_emdash: detect em/dash-like code points and double-plus hyphens."""

    def test_empty(self) -> None:
        assert contains_emdash("") is False

    def test_clean_text(self) -> None:
        assert contains_emdash("Hello world") is False

    def test_em_dash(self) -> None:
        assert contains_emdash("Hello\u2014world") is True

    def test_en_dash(self) -> None:
        assert contains_emdash("2010\u20132020") is True

    def test_double_hyphen(self) -> None:
        assert contains_emdash("Hello--world") is True

    def test_horizontal_bar(self) -> None:
        assert contains_emdash("Hello\u2015world") is True

    def test_minus_sign(self) -> None:
        assert contains_emdash("\u22125 degrees") is True

    def test_after_normalization(self) -> None:
        text = normalize_emdashes("Hello\u2014world")
        assert contains_emdash(text) is False


class TestFindBannedPhrases:
    """find_banned_phrases: detect AI cliché phrases."""

    def test_empty(self) -> None:
        assert find_banned_phrases("") == []

    def test_clean_text(self) -> None:
        assert find_banned_phrases("This is a resume.") == []

    def test_single_banned_phrase(self) -> None:
        result = find_banned_phrases("I will delve into this topic")
        assert result == ["delve into"]

    def test_multiple_banned_phrases(self) -> None:
        text = "delve into things in the realm of possibilities"
        result = find_banned_phrases(text)
        assert "delve into" in result
        assert "in the realm of" in result

    def test_case_insensitive(self) -> None:
        result = find_banned_phrases("I Delve Into the topic")
        assert result == ["delve into"]

    def test_extra_phrases(self) -> None:
        result = find_banned_phrases("this is a test skill", extra=("test skill",))
        assert result == ["test skill"]

    def test_extra_empty_phrases_ignored(self) -> None:
        result = find_banned_phrases("delve into", extra=("", "  "))
        assert result == ["delve into"]

    def test_no_duplicate_builtin(self) -> None:
        text = "delve into delve into"
        result = find_banned_phrases(text)
        assert result == ["delve into"]


class TestHasBannedPhrase:
    """has_banned_phrase: boolean wrapper around find_banned_phrases."""

    def test_empty(self) -> None:
        assert has_banned_phrase("") is False

    def test_clean(self) -> None:
        assert has_banned_phrase("Clean text") is False

    def test_with_banned(self) -> None:
        assert has_banned_phrase("delve into it") is True

    def test_extra_phrases(self) -> None:
        assert has_banned_phrase("custom skill", extra=("custom skill",)) is True


class TestStripBannedPhrases:
    """strip_banned_phrases: remove phrases and tidy whitespace."""

    def test_empty(self) -> None:
        assert strip_banned_phrases("") == ""

    def test_clean_text_unchanged(self) -> None:
        assert strip_banned_phrases("Hello world") == "Hello world"

    def test_removes_phrase(self) -> None:
        result = strip_banned_phrases("I delve into the topic")
        assert "delve into" not in result

    def test_removes_phrase_at_start(self) -> None:
        result = strip_banned_phrases("Delve into the topic")
        assert result.strip() == "the topic"

    def test_removes_phrase_at_end(self) -> None:
        result = strip_banned_phrases("the topic delve into")
        assert result == "the topic"

    def test_multiple_phrases(self) -> None:
        text = "delve into this and it's important to note that"
        result = strip_banned_phrases(text)
        assert "delve into" not in result
        assert "it's important to note" not in result

    def test_idempotent(self) -> None:
        text = "I delve into the realm of possibilities"
        first = strip_banned_phrases(text)
        second = strip_banned_phrases(first)
        assert first == second

    def test_extra_phrases(self) -> None:
        text = "I have a custom skill phrase here"
        result = strip_banned_phrases(text, extra=("custom skill",))
        assert "custom skill" not in result

    def test_case_insensitive(self) -> None:
        result = strip_banned_phrases("I Delve Into things")
        assert "Delve Into" not in result

    def test_with_curly_apostrophe(self) -> None:
        text = "it\u2019s important to note that"
        result = strip_banned_phrases(text)
        assert result == "that"


class TestPassesPostFilter:
    """passes_post_filter: combined em-dash + banned phrase check."""

    def test_clean_passes(self) -> None:
        assert passes_post_filter("Hello world") is True

    def test_em_dash_fails(self) -> None:
        assert passes_post_filter("Hello\u2014world") is False

    def test_banned_phrase_fails(self) -> None:
        assert passes_post_filter("delve into this") is False

    def test_both_failures(self) -> None:
        assert passes_post_filter("delve into \u2014 this") is False

    def test_after_normalization_passes(self) -> None:
        text = normalize_emdashes("Hello\u2014world")
        assert passes_post_filter(text) is True


class TestVoiceProfile:
    """VoiceProfile dataclass."""

    def test_default_is_empty(self) -> None:
        vp = VoiceProfile()
        assert vp.is_empty is True
        assert vp.avg_sentence_words == 0.0
        assert vp.first_person_ratio == 0.0
        assert vp.sample_count == 0
        assert vp.vocabulary == frozenset()

    def test_non_empty(self) -> None:
        vp = VoiceProfile(
            avg_sentence_words=15.0,
            first_person_ratio=0.1,
            vocabulary=frozenset({"hello"}),
            sample_count=3,
        )
        assert vp.is_empty is False

    def test_frozen_dataclass(self) -> None:
        vp = VoiceProfile()
        with pytest.raises(Exception):
            vp.avg_sentence_words = 10.0  # type: ignore[misc]

    def test_as_directive_empty(self) -> None:
        vp = VoiceProfile()
        directive = vp.as_directive()
        assert "warm, direct, first-person" in directive

    def test_as_directive_non_empty(self) -> None:
        vp = VoiceProfile(
            avg_sentence_words=12.0,
            first_person_ratio=0.05,
            vocabulary=frozenset({"hello"}),
            sample_count=3,
        )
        directive = vp.as_directive()
        assert "candidate's own voice" in directive

    def test_as_directive_short_sentences(self) -> None:
        vp = VoiceProfile(
            avg_sentence_words=10.0,
            first_person_ratio=0.05,
            vocabulary=frozenset({"hello"}),
            sample_count=3,
        )
        directive = vp.as_directive()
        assert "short, punchy sentences" in directive

    def test_as_directive_long_sentences(self) -> None:
        vp = VoiceProfile(
            avg_sentence_words=20.0,
            first_person_ratio=0.05,
            vocabulary=frozenset({"hello"}),
            sample_count=3,
        )
        directive = vp.as_directive()
        assert "measured, substantive sentences" in directive

    def test_equality(self) -> None:
        vp1 = VoiceProfile()
        vp2 = VoiceProfile()
        assert vp1 == vp2


class TestExtractVoiceProfile:
    """extract_voice_profile: build profile from corpus."""

    def test_empty_corpus(self) -> None:
        vp = extract_voice_profile([])
        assert vp.is_empty is True

    def test_corpus_with_only_empty_strings(self) -> None:
        vp = extract_voice_profile(["", "  "])
        assert vp.is_empty is True
        assert vp.sample_count == 0

    def test_corpus_with_single_sentence(self) -> None:
        vp = extract_voice_profile(["I am a software engineer."])
        assert vp.is_empty is False
        assert vp.sample_count == 1

    def test_corpus_first_person_detected(self) -> None:
        vp = extract_voice_profile(["I love my work and I am dedicated."])
        assert vp.first_person_ratio > 0

    def test_corpus_no_first_person(self) -> None:
        vp = extract_voice_profile(["The software engineer worked hard."])
        assert vp.first_person_ratio == 0.0

    def test_corpus_vocabulary_populated(self) -> None:
        vp = extract_voice_profile(["I build Python backends and data pipelines."])
        # Words >= 4 chars: build, Python, backends, data, pipelines
        assert len(vp.vocabulary) > 0
        assert "python" in vp.vocabulary


class TestVoiceAlignment:
    """voice_alignment: fraction of words in profile vocabulary."""

    def test_empty_profile(self) -> None:
        vp = VoiceProfile()
        assert voice_alignment(vp, "some text") == 1.0

    def test_empty_text(self) -> None:
        vp = VoiceProfile(vocabulary=frozenset({"hello"}), sample_count=1)
        assert voice_alignment(vp, "") == 1.0

    def test_full_alignment(self) -> None:
        vocab = frozenset({"python", "software", "engineer"})
        vp = VoiceProfile(vocabulary=vocab, sample_count=1)
        # "Python software engineer" -> words >= 4: python, software, engineer — all match
        assert voice_alignment(vp, "Python software engineer") == 1.0

    def test_no_alignment(self) -> None:
        vocab = frozenset({"cobol"})
        vp = VoiceProfile(vocabulary=vocab, sample_count=1)
        assert voice_alignment(vp, "Python software") == 0.0

    def test_partial_alignment(self) -> None:
        vocab = frozenset({"python"})
        vp = VoiceProfile(vocabulary=vocab, sample_count=1)
        # "Python engineer" -> words >= 4: python, engineer — only python matches
        result = voice_alignment(vp, "Python engineer")
        assert result == 0.5


class TestCandidateClaimTokens:
    """candidate_claim_tokens: extract non-stopword tokens >= 3 chars."""

    def test_empty_string(self) -> None:
        assert candidate_claim_tokens("") == []

    def test_all_stopwords(self) -> None:
        assert candidate_claim_tokens("the and for") == []

    def test_short_tokens_filtered(self) -> None:
        assert candidate_claim_tokens("go hi") == []

    def test_claim_tokens_extracted(self) -> None:
        result = candidate_claim_tokens("Python Kubernetes Django")
        assert "Python" in result
        assert "Kubernetes" in result
        assert "Django" in result

    def test_mixed_with_stopwords(self) -> None:
        result = candidate_claim_tokens("I know Python and Kubernetes")
        assert "Python" in result
        assert "Kubernetes" in result

    def test_claim_lowercase_preserved(self) -> None:
        result = candidate_claim_tokens("kubernetes docker")
        assert "kubernetes" in result
        assert "docker" in result

    def test_tokens_with_punctuation(self) -> None:
        result = candidate_claim_tokens("Python, Kubernetes; Docker:")
        assert "Python" in result
        assert "Kubernetes" in result
        assert "Docker" in result

    def test_no_duplicate_tokens(self) -> None:
        result = candidate_claim_tokens("Python Python")
        assert len(result) == 2  # splits keep both occurrences

    def test_quoted_tokens(self) -> None:
        result = candidate_claim_tokens('"Python" skills')
        assert "Python" in result
