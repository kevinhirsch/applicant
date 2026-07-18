"""Tests for applicant.evaluation.material_judge."""

import pytest
from dataclasses import FrozenInstanceError

from applicant.evaluation.material_judge import (
    DEFAULT_RUBRIC,
    MaterialJudgment,
    MaterialQualityScore,
    _heuristic_score_dimension,
    _parse_judge_response,
    _score_dimension,
    judge_material,
)


@pytest.fixture(autouse=True)
def _no_state_leak():
    """No module-level cache to clear; present for parallel-safety consistency."""
    yield


class TestMaterialQualityScore:
    """Tests for MaterialQualityScore frozen dataclass."""

    def test_create_with_all_fields(self):
        score = MaterialQualityScore(dimension="truthfulness", score=4, rationale="Good")
        assert score.dimension == "truthfulness"
        assert score.score == 4
        assert score.rationale == "Good"

    def test_frozen(self):
        score = MaterialQualityScore(dimension="relevance", score=3, rationale="OK")
        with pytest.raises(FrozenInstanceError):
            score.score = 5  # type: ignore[misc]


class TestMaterialJudgment:
    """Tests for MaterialJudgment frozen dataclass."""

    def test_minimal_fields(self):
        judgment = MaterialJudgment(material_id="m1", material_type="resume", overall_score=4.0)
        assert judgment.material_id == "m1"
        assert judgment.material_type == "resume"
        assert judgment.overall_score == 4.0
        assert judgment.dimension_scores == ()
        assert judgment.summary == ""
        assert judgment.errors == ()

    def test_with_dimension_scores(self):
        scores = (
            MaterialQualityScore("truthfulness", 4, "Good"),
            MaterialQualityScore("relevance", 3, "OK"),
        )
        judgment = MaterialJudgment(
            material_id="m2",
            material_type="cover_letter",
            overall_score=3.5,
            dimension_scores=scores,
            summary="Cover letter quality: 3.5/5.0",
            errors=(),
        )
        assert len(judgment.dimension_scores) == 2
        assert judgment.dimension_scores[0].dimension == "truthfulness"
        assert judgment.dimension_scores[1].dimension == "relevance"
        assert judgment.dimension_scores[0].score == 4

    def test_frozen(self):
        judgment = MaterialJudgment(material_id="m1", material_type="resume", overall_score=3.0)
        with pytest.raises(FrozenInstanceError):
            judgment.overall_score = 5.0  # type: ignore[misc]


class TestDefaultRubric:
    """Tests for DEFAULT_RUBRIC dictionary structure."""

    def test_has_expected_dimensions(self):
        assert set(DEFAULT_RUBRIC.keys()) == {
            "truthfulness",
            "relevance",
            "completeness",
            "formatting",
            "specificity",
        }

    def test_all_descriptions_are_non_empty_strings(self):
        for key, desc in DEFAULT_RUBRIC.items():
            assert isinstance(desc, str), f"Description for '{key}' is not a string"
            assert len(desc) > 0, f"Description for '{key}' is empty"

    def test_descriptions_have_content(self):
        for key, desc in DEFAULT_RUBRIC.items():
            assert len(desc) > 10, f"Description for '{key}' is too short: {desc!r}"


class TestParseJudgeResponse:
    """Tests for _parse_judge_response."""

    def test_none_returns_neutral(self):
        score, rationale = _parse_judge_response(None)
        assert score == 3
        assert rationale == "Judge returned an empty response; scored neutral."

    def test_empty_string_returns_neutral(self):
        score, rationale = _parse_judge_response("")
        assert score == 3
        assert rationale == "Judge returned an empty response; scored neutral."

    def test_whitespace_only_returns_neutral(self):
        score, rationale = _parse_judge_response("   ")
        assert score == 3
        assert rationale == "Judge returned an empty response; scored neutral."

    def test_valid_raw_json(self):
        text = '{"score": 5, "rationale": "Excellent material."}'
        score, rationale = _parse_judge_response(text)
        assert score == 5
        assert rationale == "Excellent material."

    def test_raw_json_empty_rationale_defaults(self):
        text = '{"score": 2, "rationale": ""}'
        score, rationale = _parse_judge_response(text)
        assert score == 2
        assert rationale == "LLM-judged"

    def test_fenced_json(self):
        text = (
            "Here is my evaluation:\n"
            '```json\n{"score": 4, "rationale": "Good job."}\n'
            "```\nMore text."
        )
        score, rationale = _parse_judge_response(text)
        assert score == 4
        assert rationale == "Good job."

    def test_fenced_no_language_tag(self):
        text = 'Result:\n```\n{"score": 3, "rationale": "Average."}\n```'
        score, rationale = _parse_judge_response(text)
        assert score == 3
        assert rationale == "Average."

    def test_brace_extraction(self):
        text = 'Some prose. {"score": 5, "rationale": "Great."} And trailing text.'
        score, rationale = _parse_judge_response(text)
        assert score == 5
        assert rationale == "Great."

    def test_bare_score_regex_colon(self):
        text = 'The material quality is good. "score": 4. The end.'
        score, rationale = _parse_judge_response(text)
        assert score == 4
        assert rationale == "Parsed score from a non-JSON reply."

    def test_bare_score_regex_equals(self):
        text = "the final score = 5 - its fine"
        score, rationale = _parse_judge_response(text)
        assert score == 5

    def test_bare_score_regex_no_quotes(self):
        text = "score: 2 out of 5"
        score, rationale = _parse_judge_response(text)
        assert score == 2

    def test_multi_digit_score_does_not_match(self):
        """'score: 10' must NOT match the single-digit regex."""
        text = '"score": 10 out of 10'
        score, rationale = _parse_judge_response(text)
        assert score == 3
        assert rationale == "Judge response could not be parsed; scored neutral."

    def test_no_valid_match_returns_neutral(self):
        text = "This is completely unparseable. No JSON, no score, nothing."
        score, rationale = _parse_judge_response(text)
        assert score == 3
        assert rationale == "Judge response could not be parsed; scored neutral."

    def test_nested_braces_no_json(self):
        text = "This is {score: 3} not valid json"
        score, rationale = _parse_judge_response(text)
        assert score == 3


class TestHeuristicScoreDimension:
    """Tests for _heuristic_score_dimension on each dimension."""

    def test_short_text_returns_score_1(self):
        score = _heuristic_score_dimension("truthfulness", "desc", "Hi", "resume")
        assert score.score == 1
        assert "too short" in score.rationale.lower()

    # --- truthfulness ---

    def test_truthfulness_no_profile_facts(self):
        text = "This is a longer text for testing purposes with enough words to pass the threshold."
        score = _heuristic_score_dimension("truthfulness", "desc", text, "resume")
        assert score.score == 3
        assert "no profile facts" in score.rationale.lower()

    def test_truthfulness_high_coverage(self):
        facts = {"company": "Acme Corp", "role": "Engineer", "years": "5"}
        text = "Worked at Acme Corp as an Engineer for 5 years."
        score = _heuristic_score_dimension(
            "truthfulness", "desc", text, "resume", profile_facts=facts
        )
        assert score.score == 4
        assert "3/3" in score.rationale

    def test_truthfulness_low_coverage(self):
        facts = {
            "company": "Acme Corp",
            "role": "Engineer",
            "years": "5",
            "degree": "PhD",
            "university": "MIT",
        }
        text = "I have worked at Acme Corp for many years as a professional managing various tasks and projects successfully in different domains."
        score = _heuristic_score_dimension(
            "truthfulness", "desc", text, "resume", profile_facts=facts
        )
        assert score.score == 3
        assert "1/5" in score.rationale

    # --- relevance ---

    def test_relevance_no_job_description(self):
        text = "This is a longer text for testing purposes with enough words to pass the threshold."
        score = _heuristic_score_dimension("relevance", "desc", text, "resume")
        assert score.score == 3
        assert "no job description" in score.rationale.lower()

    def test_relevance_high_overlap(self):
        text = "Python developer with Django experience and strong communication skills and AWS cloud deployment team leadership experience"
        jd = "Python developer Django communication skills cloud infrastructure AWS deployment team leadership experience"
        score = _heuristic_score_dimension(
            "relevance", "desc", text, "resume", job_description=jd
        )
        assert score.score == 4
        assert "share" in score.rationale.lower()

    def test_relevance_low_overlap(self):
        text = "An experienced Python developer with strong Django framework experience building web applications with SQL databases"
        jd = "Cloud infrastructure DevOps Kubernetes Docker CI/CD pipelines"
        score = _heuristic_score_dimension(
            "relevance", "desc", text, "resume", job_description=jd
        )
        assert score.score == 3
        assert "overlap" in score.rationale.lower()

    # --- completeness ---

    def test_completeness_high_section_coverage(self):
        text = "Summary: I am a developer. Experience: Worked at X. Education: MIT. Skills: Python. Contact: email@test.com"
        score = _heuristic_score_dimension("completeness", "desc", text, "resume")
        assert score.score == 4
        assert "5/5" in score.rationale

    def test_completeness_medium_coverage(self):
        text = "I have excellent Skills: Python and strong Contact skills available at email@test.com for prospective employers and recruiters."
        score = _heuristic_score_dimension("completeness", "desc", text, "resume")
        assert score.score == 2
        assert "2/5" in score.rationale

    def test_completeness_zero_coverage(self):
        text = "This is a longer text for testing purposes with enough words to pass the threshold."
        score = _heuristic_score_dimension("completeness", "desc", text, "resume")
        assert score.score == 2
        assert "0/5" in score.rationale

    # --- formatting ---

    def test_formatting_long_text_gets_bonus(self):
        text = "This is a very long testing sentence with enough words to pass the minimum ten word requirement and also exceed five hundred characters in total length. " * 8
        score = _heuristic_score_dimension("formatting", "desc", text, "resume")
        assert score.score == 4

    def test_formatting_short_no_punctuation(self):
        text = "some text without ending punctuation but long enough to avoid the 10-word penalty"
        score = _heuristic_score_dimension("formatting", "desc", text, "resume")
        assert score.score == 3
        assert "Material is short" in score.rationale

    def test_formatting_short_without_sentence_end(self):
        text = "A" * 10  # Short AND no sentence-ending punctuation
        # 10 words: this trips the 10-word minimum first
        score = _heuristic_score_dimension("formatting", "desc", text, "resume")
        assert score.score == 1  # short text (< 10 words) returns 1
        assert "too short" in score.rationale.lower()

    # --- specificity ---

    def test_specificity_many_numbers(self):
        text = "Increased sales by 30% in 2024, managed 15 people, reduced costs by 20% over 3 years, achieved 10 certifications, saved 500 hours."
        score = _heuristic_score_dimension("specificity", "desc", text, "resume")
        assert score.score == 4
        assert "quantified" in score.rationale.lower() or "metrics" in score.rationale.lower()

    def test_specificity_few_numbers(self):
        text = "The candidate had excellent results with 42 major projects completed last year alone and many more in progress."
        score = _heuristic_score_dimension("specificity", "desc", text, "resume")
        assert score.score == 2
        assert "1" in score.rationale

    # --- unknown dimension ---

    def test_unknown_dimension_falls_back(self):
        text = "This is a longer text for testing purposes with enough words to pass the threshold."
        score = _heuristic_score_dimension("unknown_dim", "desc", text, "resume")
        assert score.score == 3
        assert "heuristic fallback" in score.rationale.lower()


class TestScoreDimension:
    """Tests for _score_dimension delegation."""

    def test_without_llm_client_calls_heuristic(self):
        text = "This is a longer text for testing purposes with enough words to pass the threshold."
        score = _score_dimension("truthfulness", "testing", text, "resume")
        assert isinstance(score, MaterialQualityScore)
        # No profile facts -> truthfulness returns 3
        assert score.score == 3

    def test_with_llm_client_parses_response(self):
        class _MockClient:
            class _Result:
                def __init__(self, text):
                    self.text = text

            def complete(self, messages):
                return self._Result('{"score": 4, "rationale": "Good dimension."}')

        text = "This is a longer text for testing purposes with enough words to pass the threshold."
        score = _score_dimension("truthfulness", "desc", text, "resume", llm_client=_MockClient())
        assert isinstance(score, MaterialQualityScore)
        assert score.score == 4
        assert score.rationale == "Good dimension."

    def test_with_llm_client_bare_score_fallback(self):
        class _MockClient:
            class _Result:
                def __init__(self, text):
                    self.text = text

            def complete(self, messages):
                return self._Result('"score": 2')

        text = "This is a longer text for testing purposes with enough words to pass the threshold."
        score = _score_dimension("truthfulness", "desc", text, "resume", llm_client=_MockClient())
        assert isinstance(score, MaterialQualityScore)
        assert score.score == 2
        assert "non-JSON reply" in score.rationale

    def test_with_llm_client_failure_falls_back_to_heuristic(self):
        class _FailingMock:
            def complete(self, messages):
                raise RuntimeError("API error")

        text = "This is a longer text for testing purposes with enough words to pass the threshold."
        score = _score_dimension("truthfulness", "desc", text, "resume", llm_client=_FailingMock())
        assert isinstance(score, MaterialQualityScore)
        # Falls back to heuristic -> truthfulness with no profile facts -> 3
        assert score.score == 3


class TestJudgeMaterial:
    """Tests for judge_material function."""

    def test_none_text_returns_error_judgment(self):
        judgment = judge_material(None, "resume", "m1")
        assert judgment.material_id == "m1"
        assert judgment.material_type == "resume"
        assert judgment.overall_score == 0.0
        assert "material_text is None" in judgment.summary
        assert "material_text must not be None" in judgment.errors
        assert len(judgment.errors) == 1
        assert judgment.dimension_scores == ()

    def test_rubric_override(self):
        custom_rubric = {
            "custom_dim": "Custom evaluation dimension.",
        }
        text = "This is a longer text for testing purposes with enough words to pass the threshold."
        judgment = judge_material(text, "resume", "m1", rubric=custom_rubric)
        assert len(judgment.dimension_scores) == 1
        assert judgment.dimension_scores[0].dimension == "custom_dim"
        # Unknown dim fallback returns 3
        assert judgment.dimension_scores[0].score == 3

    def test_default_rubric_has_five_dimensions(self):
        text = "This is a longer text for testing purposes with enough words to pass the threshold."
        judgment = judge_material(text, "resume", "m1")
        assert len(judgment.dimension_scores) == 5
        dimensions = {s.dimension for s in judgment.dimension_scores}
        assert dimensions == {
            "truthfulness",
            "relevance",
            "completeness",
            "formatting",
            "specificity",
        }

    def test_overall_score_is_average(self):
        text = "This is a longer text for testing purposes with enough words to pass the threshold."
        judgment = judge_material(text, "resume", "m1")
        # All 5 dimensions score between 2-4, so overall should be in that range
        assert 2.0 <= judgment.overall_score <= 4.0

    def test_resume_summary_format(self):
        text = "This is a longer text for testing purposes with enough words to pass the threshold."
        judgment = judge_material(text, "resume", "m1")
        assert "Resume quality" in judgment.summary

    def test_cover_letter_summary_format(self):
        text = "This is a longer text for testing purposes with enough words to pass the threshold."
        judgment = judge_material(text, "cover_letter", "cl1")
        assert "Cover letter quality" in judgment.summary

    def test_other_material_type_summary(self):
        text = "This is a longer text for testing purposes with enough words to pass the threshold."
        judgment = judge_material(text, "screening_answer", "sa1")
        assert "Material quality" in judgment.summary

    def test_errors_accumulate_when_scoring_fails(self, monkeypatch):
        def _raise(*args, **kwargs):
            raise ValueError("Scoring failure")

        monkeypatch.setattr(
            "applicant.evaluation.material_judge._score_dimension", _raise
        )
        text = "Some text."
        judgment = judge_material(text, "resume", "m1")
        assert len(judgment.errors) == 5  # One per rubric dimension
        assert "Scoring failure" in judgment.errors[0]
        # Each error dimension gets a 1 with the error message
        assert judgment.overall_score == 1.0

    def test_no_errors_with_normal_text(self):
        text = "This is a longer text for testing purposes with enough words to pass the threshold."
        judgment = judge_material(text, "resume", "m1")
        assert len(judgment.errors) == 0
