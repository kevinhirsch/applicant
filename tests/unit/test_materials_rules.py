"""Unit tests for the pure material-generation rules (Phase 3 part B).

Covers the cover-letter on-demand decision (FR-RESUME-10), the screening
factual/essay/sensitive classifier (FR-ANSWER-1), and the aggressiveness dial
clamp/directive (FR-RESUME-9, dormant per FR-UI-2).
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
    should_generate_cover_letter,
)


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
        "Are you authorized to work in the US?",
        "What is your desired salary?",
        "Do you require sponsorship? yes/no",
    ],
)
def test_factual_questions_classified_factual(question):
    assert classify_screening_question(question) is ScreeningKind.FACTUAL


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
