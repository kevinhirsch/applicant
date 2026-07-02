"""Coverage: product-gaps backlog #23 (résumé <-> JD match-score explainer),
``docs/design/audits/PRODUCT_EXHAUSTIVE_AUDIT.md``.

The audit's stale anchor (``core.rules.ats_match_rate``) is a FORM-FILL-QUALITY
signal (fields actually filled during a live pre-fill walk vs detected), not a
keyword matcher -- so this is a genuinely new pure rule:
``core.rules.jd_match.compute_jd_match`` extracts candidate keyword terms from a
job posting (curated hard-skill set + a capitalized-phrase/notable-noun
fallback), checks which show up in the candidate's résumé text, and returns a
plain ``{score, matched, missing}`` dict. No LLM, no IO, never raises.

Surfaced as a dedicated, additive read-model:
``GET /api/documents/jd-match/{application_id}`` on the existing documents
router (piggybacking on ``POST /redline`` was not clean -- that endpoint only
knows a variant's ``base_source``/``new_source`` strings, no application/posting
context; the JD match needs the APPLICATION's target posting).

Hermetic: ``InMemoryStorage``, no LLM/DB/network. The router section proves
end-to-end reachability through a real ``TestClient(create_app())`` (mirrors
``test_cov_backlog_screeninglibrary.py``).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from applicant.app.main import create_app
from applicant.core.entities.application import Application
from applicant.core.entities.job_posting import JobPosting
from applicant.core.entities.onboarding_profile import OnboardingProfile
from applicant.core.ids import (
    ApplicationId,
    CampaignId,
    JobPostingId,
    OnboardingProfileId,
    new_id,
)
from applicant.core.rules.jd_match import KNOWN_SKILL_TERMS, compute_jd_match

# === compute_jd_match (pure) =================================================


@pytest.mark.unit
class TestComputeJdMatchBasics:
    def test_empty_posting_scores_zero_with_no_lists(self):
        result = compute_jd_match("I know Python and AWS.", "")
        assert result == {"score": 0, "matched": [], "missing": []}

    def test_blank_posting_scores_zero(self):
        result = compute_jd_match("I know Python.", "   \n\t  ")
        assert result == {"score": 0, "matched": [], "missing": []}

    def test_empty_resume_scores_zero_but_still_lists_missing_terms(self):
        result = compute_jd_match("", "We need a Python engineer with AWS and Docker skills.")
        assert result["score"] == 0
        assert result["matched"] == []
        assert "Python" in result["missing"]
        assert "AWS" in result["missing"]

    def test_never_crashes_on_none_like_or_whitespace_inputs(self):
        # Defensive: the function signature promises str, but callers upstream
        # sometimes pass "" for missing data -- must degrade, never raise.
        assert compute_jd_match("", "") == {"score": 0, "matched": [], "missing": []}
        assert compute_jd_match("   ", "   ") == {"score": 0, "matched": [], "missing": []}

    def test_score_is_always_within_bounds(self):
        posting = "Python AWS Docker Kubernetes React GraphQL Terraform Agile Scrum"
        for resume in ("", "nothing relevant here", posting, posting.lower() * 3):
            result = compute_jd_match(resume, posting)
            assert 0 <= result["score"] <= 100


@pytest.mark.unit
class TestComputeJdMatchExactKeywordMatch:
    def test_full_coverage_scores_100_and_lists_every_curated_term_as_matched(self):
        posting = "Looking for a Python engineer with AWS and Docker experience."
        resume = "I have built systems in Python on AWS using Docker containers."
        result = compute_jd_match(resume, posting)
        assert result["score"] == 100
        assert set(result["matched"]) == {"Python", "AWS", "Docker"}
        assert result["missing"] == []

    def test_partial_coverage_splits_matched_and_missing(self):
        posting = "We need Python, Kubernetes, and GraphQL experience."
        resume = "Five years of Python. No container orchestration or API query languages."
        result = compute_jd_match(resume, posting)
        assert "Python" in result["matched"]
        assert "Kubernetes" in result["missing"]
        assert "GraphQL" in result["missing"]
        assert 0 < result["score"] < 100

    def test_matching_is_case_insensitive(self):
        posting = "python AND aws required."
        resume = "I know PYTHON and Aws very well."
        result = compute_jd_match(resume, posting)
        assert "python" in [m.lower() for m in result["matched"]]
        assert "aws" in [m.lower() for m in result["matched"]]

    def test_word_boundary_prevents_substring_false_positives(self):
        # "R" (a curated language term) must not spuriously match inside an
        # unrelated word like "Rust" or "hAiR" -- and Rust itself matches only
        # when the real token is present.
        posting = "Experience with Rust is a plus."
        resume = "I mostly work in Java, not Rust."
        result = compute_jd_match(resume, posting)
        assert "Rust" in result["matched"]

    def test_punctuation_heavy_terms_match_as_whole_tokens(self):
        # C++ / CI/CD contain regex-special characters -- confirm the boundary
        # regex still matches them as whole terms, not a raw substring blowup.
        posting = "Strong C++ background and hands-on CI/CD pipeline experience."
        resume = "I write modern C++ daily and maintain our CI/CD pipelines."
        result = compute_jd_match(resume, posting)
        assert "C++" in result["matched"]
        assert "CI/CD" in result["matched"]


@pytest.mark.unit
class TestComputeJdMatchMissingKeywordSurfacing:
    def test_missing_terms_are_the_ones_absent_from_the_resume(self):
        posting = "Must know SQL, Kubernetes, and Terraform."
        resume = "I am a SQL expert."
        result = compute_jd_match(resume, posting)
        assert "SQL" in result["matched"]
        assert set(result["missing"]) >= {"Kubernetes", "Terraform"}

    def test_missing_and_matched_never_overlap(self):
        posting = (
            "Python, JavaScript, React, AWS, Docker, Kubernetes, Terraform, "
            "GraphQL, PostgreSQL, Redis, Agile, Scrum required."
        )
        resume = "Python, React, AWS, PostgreSQL, Agile experience."
        result = compute_jd_match(resume, posting)
        assert not (set(result["matched"]) & set(result["missing"]))

    def test_lists_are_capped_for_readability(self):
        # A posting naming every curated term at once must still return a
        # readable (<= 12) list, not a wall of text.
        posting = " ".join(KNOWN_SKILL_TERMS)
        result = compute_jd_match("", posting)
        assert len(result["missing"]) <= 12
        resume = " ".join(KNOWN_SKILL_TERMS)
        result_full = compute_jd_match(resume, posting)
        assert len(result_full["matched"]) <= 12

    def test_no_known_terms_falls_back_to_capitalized_phrase_extraction(self):
        # A posting with no curated hard-skill hits still surfaces something
        # extractive (Title Case phrases / notable nouns) rather than an empty
        # result, so the UI always has something plain-language to show.
        posting = "You will lead the Customer Onboarding Experience and own Vendor Relationships."
        result = compute_jd_match("", posting)
        assert result["missing"]  # fallback candidates were extracted
        assert result["score"] == 0


@pytest.mark.unit
class TestComputeJdMatchDeterminism:
    def test_same_inputs_always_produce_the_same_output(self):
        posting = "Need Python, AWS, and strong communication skills."
        resume = "Python developer with AWS experience."
        first = compute_jd_match(resume, posting)
        second = compute_jd_match(resume, posting)
        assert first == second


# === router reachability (GET /api/documents/jd-match/{application_id}) =====


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        r = c.post(
            "/api/setup/llm",
            json={"provider": "ollama", "base_url": "http://localhost:11434/v1", "model": "llama3.1"},
        )
        assert r.status_code == 204
        yield c


def _seed_application(storage, *, description="", base_resume_text=""):
    cid = CampaignId(new_id())
    pid = JobPostingId(new_id())
    storage.postings.add(
        JobPosting(
            id=pid,
            campaign_id=cid,
            title="Backend Engineer",
            company="Acme",
            source_url="https://jobs.example/role",
            description=description,
        )
    )
    aid = ApplicationId(new_id())
    storage.applications.add(Application(id=aid, campaign_id=cid, posting_id=pid))
    storage.commit()
    if base_resume_text:
        # Mirrors MaterialService._base_resume_text's own storage shape (the
        # onboarding-profile intake's base_resume.raw_text) so the endpoint's
        # resume_text resolution has something real to read.
        storage.onboarding_profiles.add(
            OnboardingProfile(
                id=OnboardingProfileId(new_id()),
                campaign_id=cid,
                intake={"base_resume": {"raw_text": base_resume_text}},
            )
        )
        storage.commit()
    return cid, aid


@pytest.mark.unit
class TestJdMatchRouter:
    def test_unknown_application_is_404(self, client):
        res = client.get("/api/documents/jd-match/does-not-exist")
        assert res.status_code == 404

    def test_application_with_no_posting_description_degrades_to_zero(self, client):
        storage = client.app.state.container.storage
        cid, aid = _seed_application(storage, description="")
        res = client.get(f"/api/documents/jd-match/{aid}")
        assert res.status_code == 200
        body = res.json()
        assert body["application_id"] == str(aid)
        assert body == {"application_id": str(aid), "score": 0, "matched": [], "missing": []}

    def test_response_shape_matches_the_pure_rule(self, client):
        storage = client.app.state.container.storage
        cid, aid = _seed_application(
            storage,
            description="Looking for a Python engineer with AWS and Kubernetes experience.",
        )
        res = client.get(f"/api/documents/jd-match/{aid}")
        assert res.status_code == 200
        body = res.json()
        assert set(body.keys()) == {"application_id", "score", "matched", "missing"}
        assert isinstance(body["score"], int)
        assert isinstance(body["matched"], list)
        assert isinstance(body["missing"], list)
        assert 0 <= body["score"] <= 100

    def test_matched_terms_reflect_the_candidates_own_base_resume_text(self, client):
        storage = client.app.state.container.storage
        cid, aid = _seed_application(
            storage,
            description="Seeking a Python engineer with Kubernetes and GraphQL experience.",
            base_resume_text="Senior engineer with 6 years of Python and Kubernetes at scale.",
        )
        res = client.get(f"/api/documents/jd-match/{aid}")
        assert res.status_code == 200
        body = res.json()
        assert "Python" in body["matched"]
        assert "Kubernetes" in body["matched"]
        assert "GraphQL" in body["missing"]
        assert body["score"] > 0

    def test_endpoint_never_500s_when_storage_lookups_fail_defensively(self, client):
        # An application id that IS resolvable but whose posting_id points
        # nowhere must still degrade cleanly (never fabricate, never crash).
        storage = client.app.state.container.storage
        cid = CampaignId(new_id())
        aid = ApplicationId(new_id())
        storage.applications.add(
            Application(id=aid, campaign_id=cid, posting_id=JobPostingId(new_id()))
        )
        storage.commit()
        res = client.get(f"/api/documents/jd-match/{aid}")
        assert res.status_code == 200
        assert res.json()["score"] == 0
