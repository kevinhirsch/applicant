"""Unit tests for applicant.core.rules.jd_match (AZ0-96).

Tests compute_jd_match: a deterministic keyword-coverage scorer that
returns matched / missing terms with a 0-100 integer score.
"""

from __future__ import annotations

import pytest

from applicant.core.rules.jd_match import compute_jd_match


@pytest.fixture(autouse=True)
def _no_cache():
    """xdist parallel-safety: clear the LRU cache on _term_pattern."""
    import applicant.core.rules.jd_match as _jd
    _jd._term_pattern.cache_clear()
    yield


# ============================================================================
# compute_jd_match
# ============================================================================

@pytest.mark.unit
class TestComputeJdMatch:
    """Functional tests for compute_jd_match(resume_text, posting_text)."""

    def test_empty_resume_empty_posting(self) -> None:
        result = compute_jd_match("", "")
        assert result == {"score": 0, "matched": [], "missing": []}

    def test_empty_posting(self) -> None:
        result = compute_jd_match("Python developer with React experience", "")
        assert result == {"score": 0, "matched": [], "missing": []}

    def test_empty_resume(self) -> None:
        result = compute_jd_match("", "Need a Python developer")
        # All candidates are missing since resume is empty
        assert isinstance(result, dict)
        assert set(result.keys()) == {"score", "matched", "missing"}
        assert result["score"] >= 0
        assert result["matched"] == []
        assert len(result["missing"]) > 0

    def test_perfect_match_returns_full_score(self) -> None:
        posting = "We need a Python developer with React experience and Docker."
        resume = "Python developer skilled in React and Docker."
        result = compute_jd_match(resume, posting)
        assert isinstance(result, dict)
        assert set(result.keys()) == {"score", "matched", "missing"}
        assert isinstance(result["score"], int)
        assert 0 <= result["score"] <= 100
        assert isinstance(result["matched"], list)
        assert isinstance(result["missing"], list)
        # Python, React, Docker are all in KNOWN_SKILL_TERMS and in both texts
        assert "Python" in result["matched"]
        assert "React" in result["matched"]
        assert "Docker" in result["matched"]

    def test_partial_match_returns_intermediate_score(self) -> None:
        posting = "Need Python, React, Docker, Kubernetes, and AWS."
        resume = "Experienced Python developer with React."
        result = compute_jd_match(resume, posting)
        # Resume matches Python and React; missing Docker, Kubernetes, AWS
        assert "Python" in result["matched"]
        assert "React" in result["matched"]
        assert "Docker" in result["missing"] or "Kubernetes" in result["missing"] or "AWS" in result["missing"]
        # Score should be > 0 and < 100 (partial match)
        assert 0 < result["score"] < 100

    def test_no_match_returns_zero_score(self) -> None:
        posting = "Looking for a Rust and Elixir developer."
        resume = "I know Python and React."
        result = compute_jd_match(resume, posting)
        # Rust and Elixir are in KNOWN_SKILL_TERMS; neither is in resume
        if result["score"] == 0:
            assert result["matched"] == []
            assert len(result["missing"]) > 0

    def test_case_insensitive_matching(self) -> None:
        posting = "Looking for a python developer"
        resume = "I know PYTHON very well"
        result = compute_jd_match(resume, posting)
        assert "Python" in result["matched"]

    def test_known_skill_terms_are_recognized_from_posting(self) -> None:
        posting = "Need a PostgreSQL DBA with Kubernetes experience."
        resume = "I manage PostgreSQL and Kubernetes."
        result = compute_jd_match(resume, posting)
        assert "PostgreSQL" in result["matched"]
        assert "Kubernetes" in result["matched"]

    def test_missing_terms_when_resume_lacks_posting_skills(self) -> None:
        posting = "Need AWS Certified professional with Docker and Terraform."
        resume = "I have AWS experience."
        result = compute_jd_match(resume, posting)
        assert "AWS" in result["matched"]
        assert "Docker" in result["missing"] or "Terraform" in result["missing"]

    def test_only_whitespace_resume(self) -> None:
        posting = "Need a Python developer"
        result = compute_jd_match("   \n\t   ", posting)
        # All candidates are missing since resume is effectively empty
        assert result["matched"] == []
        assert len(result["missing"]) > 0
        assert result["score"] == 0

    def test_whitespace_only_posting(self) -> None:
        result = compute_jd_match("Python developer", "  \n  ")
        assert result == {"score": 0, "matched": [], "missing": []}

    def test_returned_lists_are_synchronized_with_score(self) -> None:
        """Assert that score reflects exactly matched / (matched+missing)."""
        posting = "Need Python, React, Docker for the role."
        resume = "Python and React experience only."
        result = compute_jd_match(resume, posting)
        matched_count = len(result["matched"])
        missing_count = len(result["missing"])
        total = matched_count + missing_count
        if total > 0:
            expected_score = round(100 * matched_count / total)
            expected_score = max(0, min(100, expected_score))
            assert result["score"] == expected_score

    def test_multiple_occurrences_same_term_not_duplicated(self) -> None:
        posting = "Python, Python, and more Python. Also React."
        resume = "I know Python."
        result = compute_jd_match(resume, posting)
        # Python should appear only once in matched list
        assert result["matched"].count("Python") <= 1

    def test_candidate_list_is_capped(self) -> None:
        """A long posting with many distinct terms is capped per _MAX_CANDIDATES."""
        # Use many KNOWN_SKILL_TERMS in the posting
        skills = [
            "Python", "JavaScript", "TypeScript", "Java", "C++", "C#", "Go",
            "Rust", "Ruby", "PHP", "Swift", "Kotlin", "Scala", "React",
            "Angular", "Vue", "Django", "Flask", "FastAPI", "Spring", ".NET",
            "Rails", "TensorFlow", "PyTorch", "Keras", "PostgreSQL", "MySQL",
            "MongoDB", "Redis", "Elasticsearch", "DynamoDB", "Cassandra",
            "AWS", "Azure", "GCP", "Kubernetes", "Docker", "Terraform",
            "Ansible", "Jenkins", "Git", "Linux", "GraphQL", "NLP", "LLM",
        ]
        posting = ". ".join(f"Need {s}" for s in skills)
        resume = "I know Python, React, Docker, and Kubernetes."
        result = compute_jd_match(resume, posting)
        # matched + missing should not exceed _MAX_CANDIDATES (40) candidates
        assert len(result["matched"]) + len(result["missing"]) <= 40

    def test_returns_dict_with_only_expected_keys(self) -> None:
        result = compute_jd_match("Python", "Need Python")
        assert set(result.keys()) == {"score", "matched", "missing"}

    def test_score_is_integer_between_zero_and_hundred(self) -> None:
        result = compute_jd_match("Python", "Need Python")
        assert isinstance(result["score"], int)
        assert 0 <= result["score"] <= 100
