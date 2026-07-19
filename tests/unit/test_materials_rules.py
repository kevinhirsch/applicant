"""Unit tests for the pure material-generation rules (Phase 3 part B).

Covers the cover-letter on-demand decision (FR-RESUME-10), the screening
factual/essay/sensitive classifier (FR-ANSWER-1), the aggressiveness dial
clamp/directive (FR-RESUME-9, dormant per FR-UI-2), and the screening
question normalisation (product-gaps #20).
"""

from __future__ import annotations

import pytest

from applicant.core.rules.materials import (
    AGGRESSIVENESS_DEFAULT,
    AGGRESSIVENESS_MAX,
    AGGRESSIVENESS_MIN,
    ScreeningKind,
    aggressiveness_directive,
    clamp_aggressiveness,
    classify_screening_question,
    normalize_screening_question,
    should_generate_cover_letter,
)


@pytest.fixture(autouse=True)
def _no_cache() -> None:
    """Parallel-execution safety: clear any module-level cache (none yet, but
    prepares for xdist)."""
    pass


# === cover letters on demand (FR-RESUME-10) ================================
@pytest.mark.unit
def test_cover_letter_off_by_default():
    assert should_generate_cover_letter() is False


@pytest.mark.unit
def test_cover_letter_campaign_default_on():
    assert should_generate_cover_letter(campaign_default=True) is True


@pytest.mark.unit
def test_cover_letter_role_override_wins_both_ways():
    assert should_generate_cover_letter(campaign_default=False, role_requires=True) is True
    assert should_generate_cover_letter(campaign_default=True, role_requires=False) is False


# === screening classification (FR-ANSWER-1) ================================
@pytest.mark.unit
@pytest.mark.parametrize(
    "question",
    [
        "How many years of Python experience do you have?",
        "What is your desired salary?",
    ],
)
def test_factual_questions_classified_factual(question):
    assert classify_screening_question(question) is ScreeningKind.FACTUAL


@pytest.mark.unit
@pytest.mark.parametrize(
    "question",
    [
        # These two classified FACTUAL before P2-7; work auth now has its own
        # never-LLM-drafted lane (see test_sensitive_question_policy.py).
        "Are you authorized to work in the US?",
        "Do you require sponsorship? yes/no",
    ],
)
def test_work_auth_questions_classified_work_auth(question):
    assert classify_screening_question(question) is ScreeningKind.WORK_AUTH


@pytest.mark.unit
@pytest.mark.parametrize(
    "question",
    [
        "Why do you want to work here?",
        "Describe a time you led a team through a hard problem.",
        "Tell us about your proudest accomplishment.",
        "In your own words, what makes you a fit?",
    ],
)
def test_essay_questions_classified_essay(question):
    assert classify_screening_question(question) is ScreeningKind.ESSAY


@pytest.mark.unit
def test_sensitive_question_classified_sensitive():
    assert classify_screening_question("What is your race/ethnicity?") is ScreeningKind.SENSITIVE
    assert (
        classify_screening_question("Are you a protected veteran?") is ScreeningKind.SENSITIVE
    )


@pytest.mark.unit
def test_essay_about_protected_attribute_is_not_sensitive():
    # FR-ATTR-6/NFR-PRIV-1: a multi-word ESSAY prompt that merely mentions a
    # protected attribute is an essay, NOT an EEO self-identification field.
    assert (
        classify_screening_question("How do you foster gender diversity on a team?")
        is ScreeningKind.ESSAY
    )
    assert (
        classify_screening_question("Describe a time you supported veterans at work.")
        is ScreeningKind.ESSAY
    )
    # An actual short EEO self-id field still classifies sensitive.
    assert classify_screening_question("Gender") is ScreeningKind.SENSITIVE


@pytest.mark.unit
def test_essay_cues_win_over_broad_factual_cues():
    # FR-ANSWER-1: essay cues ("describe a") must be checked before broad factual
    # cues ("do you have") so a mixed prompt routes to essay/review.
    assert (
        classify_screening_question("Describe a project — do you have an example?")
        is ScreeningKind.ESSAY
    )


@pytest.mark.unit
def test_ambiguous_long_question_defaults_to_essay():
    # Anything unclear routes to essay so it always passes the filters + review gate.
    assert classify_screening_question("Share more about the projects you enjoyed building.") is (
        ScreeningKind.ESSAY
    )


# === screening question normalisation (product-gaps #20) ===================
@pytest.mark.unit
def test_normalize_trailing_punctuation():
    """Collapse trailing ?.! and whitespace."""
    assert normalize_screening_question("Why this company?") == "why this company"
    assert normalize_screening_question("Why this company??") == "why this company"
    assert normalize_screening_question("Why this company!") == "why this company"
    assert normalize_screening_question("Why this company.") == "why this company"


@pytest.mark.unit
def test_normalize_internal_whitespace():
    """Collapse multiple internal spaces into one."""
    assert (
        normalize_screening_question("Why  do  you  want   this  job?")
        == "why do you want this job"
    )


@pytest.mark.unit
def test_normalize_case_insensitive():
    """Lowercase the text."""
    assert normalize_screening_question("WHY THIS COMPANY?") == "why this company"
    assert normalize_screening_question("Why This Company?") == "why this company"


@pytest.mark.unit
def test_normalize_blank_is_empty():
    """Blank/whitespace-only input returns empty string."""
    assert normalize_screening_question("") == ""
    assert normalize_screening_question("   ") == ""
    assert normalize_screening_question(None) == ""


@pytest.mark.unit
def test_normalize_returns_deterministic_key():
    """Same question with/without trailing punctuation yields same key."""
    assert normalize_screening_question("Why this company?") == normalize_screening_question(
        "why this company"
    )


@pytest.mark.unit
def test_normalize_preserves_internal_punctuation():
    """Internal punctuation like hyphens or apostrophes is preserved."""
    result = normalize_screening_question("What's your approach to C++?")
    assert "what" in result
    assert "approach" in result
    assert result == "what's your approach to c++"


# === aggressiveness dial (FR-RESUME-9, dormant per FR-UI-2) ================
@pytest.mark.unit
def test_clamp_aggressiveness_bounds_and_default():
    assert clamp_aggressiveness(None) == AGGRESSIVENESS_DEFAULT
    assert clamp_aggressiveness(-50) == AGGRESSIVENESS_MIN
    assert clamp_aggressiveness(500) == AGGRESSIVENESS_MAX
    assert clamp_aggressiveness(40) == 40
    assert clamp_aggressiveness("bad") == AGGRESSIVENESS_DEFAULT


@pytest.mark.unit
def test_aggressiveness_directive_never_licenses_fabrication():
    for v in (0, 20, 50, 80, 100):
        directive = aggressiveness_directive(v)
        assert "not in the source" in directive  # truthfulness preserved at every level


@pytest.mark.unit
def test_aggressiveness_directive_thresholds():
    """High (>=67) assertive, low (<=33) measured, middle balanced."""
    high = aggressiveness_directive(67)
    assert "assertively" in high
    low = aggressiveness_directive(33)
    assert "understated" in low
    mid = aggressiveness_directive(50)
    assert "balanced" in mid
