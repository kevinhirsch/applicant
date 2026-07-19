import pytest
from applicant.core.rules.materials import (
    AGGRESSIVENESS_DEFAULT,
    AGGRESSIVENESS_MAX,
    AGGRESSIVENESS_MIN,
    ScreeningKind,
    should_generate_cover_letter,
    classify_screening_question,
    clamp_aggressiveness,
    normalize_screening_question,
)


@pytest.fixture(autouse=True)
def _no_cache():
    pass


class TestShouldGenerateCoverLetter:
    """Tests for should_generate_cover_letter (FR-RESUME-10)."""

    @pytest.mark.parametrize(
        ("campaign_default", "role_requires", "expected"),
        [
            (False, True, True),
            (True, False, False),
            (True, True, True),
            (False, False, False),
            (False, None, False),
            (True, None, True),
            pytest.param(False, None, False, id="default_off"),
        ],
    )
    def test_cover_letter_output(self, campaign_default, role_requires, expected):
        assert should_generate_cover_letter(campaign_default=campaign_default, role_requires=role_requires) is expected

    def test_default_no_args(self):
        assert should_generate_cover_letter() is False


class TestClassifyScreeningQuestion:
    """Tests for classify_screening_question (FR-ANSWER-1, P2-7)."""

    @pytest.mark.parametrize(
        ("question", "expected_kind"),
        [
            pytest.param("", ScreeningKind.ESSAY, id="empty_string"),
            pytest.param(None, ScreeningKind.ESSAY, id="none"),
            pytest.param("What is your visa status?", ScreeningKind.WORK_AUTH, id="work_auth_visa"),
            pytest.param("Are you authorized to work in the US?", ScreeningKind.WORK_AUTH, id="work_auth_authorized"),
            pytest.param("Do you require sponsorship for employment?", ScreeningKind.WORK_AUTH, id="work_auth_sponsorship"),
            pytest.param("Tell us about your experience", ScreeningKind.ESSAY, id="essay_tell_us_about"),
            pytest.param("Describe a time you overcame a challenge", ScreeningKind.ESSAY, id="essay_describe_time"),
            pytest.param("Why do you want to work here?", ScreeningKind.ESSAY, id="essay_why_do_you_want"),
            pytest.param("How do you handle stressful situations?", ScreeningKind.ESSAY, id="essay_how_do_you"),
            pytest.param("Gender", ScreeningKind.SENSITIVE, id="sensitive_gender"),
            pytest.param("Hispanic / Latino", ScreeningKind.SENSITIVE, id="sensitive_hispanic"),
            pytest.param(
                "How do you foster gender diversity in the workplace?",
                ScreeningKind.ESSAY,
                id="essay_gender_essay",
            ),
            pytest.param("How many years of experience do you have?", ScreeningKind.FACTUAL, id="factual_years"),
            pytest.param("What is your desired pay?", ScreeningKind.FACTUAL, id="factual_desired_pay"),
            pytest.param("Do you have a valid driver's license?", ScreeningKind.FACTUAL, id="factual_do_you_have"),
            pytest.param("What is your notice period?", ScreeningKind.FACTUAL, id="factual_short_closed"),
            pytest.param("When can you start?", ScreeningKind.FACTUAL, id="factual_when_start"),
            pytest.param(
                "Please provide a detailed explanation of your approach to project management",
                ScreeningKind.ESSAY,
                id="default_essay_long",
            ),
            pytest.param(
                "Describe your work authorization status",
                ScreeningKind.WORK_AUTH,
                id="work_auth_overrides_essay_cue",
            ),
        ],
    )
    def test_classification(self, question, expected_kind):
        assert classify_screening_question(question) is expected_kind


class TestNormalizeScreeningQuestion:
    """Tests for normalize_screening_question (#20)."""

    @pytest.mark.parametrize(
        ("question", "expected"),
        [
            ("", ""),
            (None, ""),
            ("  ", ""),
            ("Why do you want to work here?", "why do you want to work here"),
            ("Why do you want to work here??", "why do you want to work here"),
            ("Why do you want to work here!", "why do you want to work here"),
            ("  Why do you want to work here?  ", "why do you want to work here"),
            ("WHY DO YOU WANT TO WORK HERE?", "why do you want to work here"),
            ("Tell us   about   yourself", "tell us about yourself"),
            ("describe  your   experience!!", "describe your experience"),
            ("How many years?", "how many years"),
            ("Salary expectation?", "salary expectation"),
            ("What?", "what"),
            ("What?!", "what"),
            ("Yes/no", "yes/no"),
            ("What is your notice period.", "what is your notice period"),
            ("a?b?c?", "a?b?c"),
            pytest.param("\tWhy here?\n", "why here", id="whitespace_surrounded"),
        ],
    )
    def test_normalization(self, question, expected):
        assert normalize_screening_question(question) == expected


class TestClampAggressiveness:
    """Tests for clamp_aggressiveness (FR-RESUME-9)."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (None, AGGRESSIVENESS_DEFAULT),
            (-50, AGGRESSIVENESS_MIN),
            (-1, AGGRESSIVENESS_MIN),
            (0, AGGRESSIVENESS_MIN),
            (20, 20),
            (50, 50),
            (100, AGGRESSIVENESS_MAX),
            (101, AGGRESSIVENESS_MAX),
            (999, AGGRESSIVENESS_MAX),
        ],
    )
    def test_clamp(self, value, expected):
        assert clamp_aggressiveness(value) == expected

    def test_constants(self):
        assert AGGRESSIVENESS_MIN == 0
        assert AGGRESSIVENESS_MAX == 100
        assert AGGRESSIVENESS_DEFAULT == 20
