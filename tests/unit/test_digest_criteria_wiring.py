"""Regression: the front-door digest must score against the campaign's SAVED criteria.

The front-door ``GET /api/digest/{id}`` builds the digest without threading criteria,
so the service previously scored every posting against *no* criteria — a uniform neutral
75 that ignored the onboarding-seeded search criteria entirely. These tests pin:
  * the digest self-loads the campaign criteria when a caller omits them;
  * viability is the configured model's semantic score when a model is available;
  * ``score_for_digest`` reuses a persisted score until the criteria change (bounds the
    repeated LLM cost on the digest hot path).
"""

from __future__ import annotations

import pytest

from applicant.adapters.embedding.local_embedding import LocalEmbedding
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.criteria_service import CriteriaService
from applicant.application.services.digest_service import DigestService
from applicant.application.services.scoring_service import ScoringService
from applicant.core.entities.campaign import Campaign
from applicant.core.entities.job_posting import JobPosting
from applicant.core.entities.search_criteria import SearchCriteria
from applicant.core.ids import CampaignId, JobPostingId, new_id
from applicant.ports.driven.llm import LLMResult


def _campaign_with_criteria(storage) -> CampaignId:
    cid = CampaignId(new_id())
    storage.campaigns.add(
        Campaign(
            id=cid,
            name="C",
            criteria={
                "titles": ["Senior Backend Engineer"],
                "keywords": ["python", "go"],
                "work_modes": ["remote"],
                "human_readable": "senior backend, python/go, remote",
            },
        )
    )
    storage.commit()
    return cid


def _add_posting(storage, cid, **kw) -> JobPostingId:
    pid = JobPostingId(new_id())
    storage.postings.add(
        JobPosting(id=pid, campaign_id=cid, source_url="http://x", **kw)
    )
    storage.commit()
    return pid


@pytest.mark.unit
def test_digest_self_loads_campaign_criteria_when_caller_omits_it():
    storage = InMemoryStorage()
    cid = _campaign_with_criteria(storage)
    _add_posting(
        storage, cid, title="Senior Backend Engineer", company="A",
        description="python go kafka",
    )
    criteria = CriteriaService(storage, llm=None)
    scoring = ScoringService(storage, llm=None, embedding=LocalEmbedding(), threshold=0)
    digest = DigestService(storage, None, scoring, criteria=criteria)

    payload = digest.build_digest_payload(cid)  # front-door path: NO criteria threaded

    # The searched summary reflects the loaded criteria (proves it was wired in)...
    assert "Senior Backend Engineer" in payload["searched"]
    # ...and the row was scored AGAINST criteria, not via the neutral no-criteria branch.
    assert payload["rows"]
    assert "No search criteria set yet" not in payload["rows"][0]["why_suggested"]


@pytest.mark.unit
def test_viability_scoring_uses_configured_model_when_available():
    storage = InMemoryStorage()
    cid = _campaign_with_criteria(storage)

    class _FakeLLM:
        def is_configured(self):
            return True

        def complete(self, messages, *, start_tier=1, json_schema=None, max_tokens=None):
            return LLMResult(
                text="", tier=1, model="fake",
                structured={"score": 91, "rationale": "great match"},
            )

    scoring = ScoringService(storage, llm=_FakeLLM(), embedding=LocalEmbedding())
    crit = CriteriaService(storage, llm=None).get_criteria(cid)
    posting = JobPosting(
        id=JobPostingId(new_id()), campaign_id=cid, title="Senior Backend Engineer",
        company="A", source_url="http://x", description="python go",
    )
    result = scoring.score_posting(posting, crit)
    assert result.score == pytest.approx(0.91)
    assert "great match" in result.rationale


@pytest.mark.unit
def test_score_for_digest_reuses_persisted_until_criteria_change():
    storage = InMemoryStorage()
    cid = _campaign_with_criteria(storage)
    crit = CriteriaService(storage, llm=None).get_criteria(cid)

    calls = {"n": 0}

    class _CountingLLM:
        def is_configured(self):
            return True

        def complete(self, messages, *, start_tier=1, json_schema=None, max_tokens=None):
            calls["n"] += 1
            return LLMResult(
                text="", tier=1, model="fake",
                structured={"score": 80, "rationale": "ok"},
            )

    scoring = ScoringService(storage, llm=_CountingLLM(), embedding=LocalEmbedding())
    pid = _add_posting(
        storage, cid, title="Senior Backend Engineer", company="A", description="python go",
    )

    s1 = scoring.score_for_digest(storage.postings.get(pid), crit)
    assert calls["n"] == 1
    # Same criteria -> reuse the persisted score, no new model call.
    s2 = scoring.score_for_digest(storage.postings.get(pid), crit)
    assert calls["n"] == 1
    assert s2.score == pytest.approx(s1.score)
    # Criteria change -> the signature changes, so it recomputes.
    changed = SearchCriteria(
        campaign_id=cid, titles=("Staff Engineer",), keywords=("rust",)
    )
    scoring.score_for_digest(storage.postings.get(pid), changed)
    assert calls["n"] == 2
