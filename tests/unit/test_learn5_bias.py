"""FR-LEARN-5 conversion-driven bias over the LIVE discrete signature + recall.

The live conversion loop (submission_service -> record_and_persist_conversion ->
AdvancedLearningService.record_conversion) folds ONLY the discrete role-feature
signature (role:/skill:/comp:/variant:/...), NOT the Phase-1 embedding centroid.
These tests prove that discovery, scoring, and résumé-variant selection lean toward
that discrete converting signature (and an advisory recall nudge) WITHOUT overriding
the user's hard criteria, and are byte-identical with no conversion history.
"""

from __future__ import annotations

import pytest

from applicant.adapters.discovery.jobspy_searxng import JobSpySearxngDiscovery
from applicant.adapters.embedding.local_embedding import LocalEmbedding
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.discovery_service import DiscoveryService
from applicant.application.services.learning_advanced import AdvancedLearningService
from applicant.application.services.learning_service import LearningService
from applicant.application.services.material_service import MaterialService
from applicant.application.services.scoring_service import ScoringService
from applicant.core.entities.application import Application
from applicant.core.entities.campaign import Campaign
from applicant.core.entities.job_posting import JobPosting
from applicant.core.entities.outcome_event import OutcomeEvent, OutcomeSource
from applicant.core.entities.resume_variant import ResumeVariant
from applicant.core.entities.search_criteria import SearchCriteria
from applicant.core.ids import (
    ApplicationId,
    CampaignId,
    JobPostingId,
    OutcomeEventId,
    ResumeVariantId,
    new_id,
)
from applicant.core.state_machine import ApplicationState
from applicant.ports.driven.recall_index import RecallHit


# --- shared fixtures -------------------------------------------------------
@pytest.fixture
def storage() -> InMemoryStorage:
    return InMemoryStorage()


@pytest.fixture
def embedding() -> LocalEmbedding:
    return LocalEmbedding()


@pytest.fixture
def campaign(storage) -> Campaign:
    c = Campaign(id=CampaignId(new_id()), name="c")
    storage.campaigns.add(c)
    storage.commit()
    return c


class _StubRecall:
    """Minimal RecallIndex stub returning canned hits keyed by query substring."""

    def __init__(self, hits_by_substring=None) -> None:
        self._hits = hits_by_substring or {}

    def index(self, run_id, text, campaign_id=None) -> None:  # pragma: no cover
        pass

    def search(self, query, *, limit=5, scope=None, campaign_id=None):
        for needle, hits in self._hits.items():
            if needle.lower() in query.lower():
                return tuple(hits[:limit])
        return ()


def _record_live_conversion(
    storage,
    advanced: AdvancedLearningService,
    campaign_id,
    *,
    job_title: str,
    work_mode: str = "remote",
    resume_variant_id=None,
    description: str = "",
):
    """Drive the LIVE conversion path: an APPROVED+submitted app folds the discrete
    converting signature (record_and_persist_conversion), NOT the Phase-1 centroid."""
    posting_id = JobPostingId(new_id())
    app = Application(
        id=ApplicationId(new_id()),
        campaign_id=campaign_id,
        posting_id=posting_id,
        status=ApplicationState.APPROVED,
        role_name=job_title,
        job_title=job_title,
        work_mode=work_mode,
        resume_variant_id=resume_variant_id,
    )
    storage.outcomes.add(
        OutcomeEvent(
            id=OutcomeEventId(new_id()),
            application_id=app.id,
            type="submitted",
            source=OutcomeSource.MANUAL,
        )
    )
    posting = None
    if description:
        posting = JobPosting(
            id=posting_id,
            campaign_id=campaign_id,
            title=job_title,
            company="Co",
            source_url="u",
            description=description,
        )
        storage.postings.add(posting)
    storage.commit()
    advanced.record_and_persist_conversion(campaign_id, app, posting=posting)
    return app


# === discovery title bias (FR-LEARN-5) ====================================
@pytest.mark.unit
def test_discovery_titles_shift_toward_live_converting_role(storage, embedding, campaign):
    base = LearningService(storage, embedding)
    advanced = AdvancedLearningService(base=base, storage=storage)
    _record_live_conversion(
        storage, advanced, campaign.id, job_title="Staff Platform Engineer"
    )

    seen = {}

    class _Capturing:
        key = "cap"

        def fetch(self, campaign_id, criteria):
            seen["titles"] = tuple(criteria.titles)
            return []

    disc = JobSpySearxngDiscovery(sources=[_Capturing()])
    svc = DiscoveryService(
        storage, disc, embedding, base, advanced_learning=advanced
    )
    svc.run_discovery(
        campaign.id, SearchCriteria(campaign_id=campaign.id, titles=("engineer",))
    )
    # The user's title is preserved AND the LIVE converting role title is folded in,
    # purely from the discrete signature the conversion wrote (no centroid). The
    # discrete signature normalizes role titles to lowercase.
    assert "engineer" in seen["titles"]
    assert "staff platform engineer" in seen["titles"]


@pytest.mark.unit
def test_discovery_unchanged_with_no_conversion_history(storage, embedding, campaign):
    base = LearningService(storage, embedding)
    advanced = AdvancedLearningService(base=base, storage=storage)

    seen = {}

    class _Capturing:
        key = "cap"

        def fetch(self, campaign_id, criteria):
            seen["titles"] = tuple(criteria.titles)
            return []

    disc = JobSpySearxngDiscovery(sources=[_Capturing()])
    svc = DiscoveryService(
        storage, disc, embedding, base, advanced_learning=advanced
    )
    svc.run_discovery(
        campaign.id, SearchCriteria(campaign_id=campaign.id, titles=("engineer",))
    )
    # No conversion => criteria titles unchanged.
    assert seen["titles"] == ("engineer",)


@pytest.mark.unit
def test_discovery_folds_recall_titles(storage, embedding, campaign):
    base = LearningService(storage, embedding)
    recall = _StubRecall(
        {"roles like": [RecallHit(run_id="r1", text="Site Reliability Engineer", score=0.9)]}
    )
    advanced = AdvancedLearningService(base=base, storage=storage, recall=recall)

    seen = {}

    class _Capturing:
        key = "cap"

        def fetch(self, campaign_id, criteria):
            seen["titles"] = tuple(criteria.titles)
            return []

    disc = JobSpySearxngDiscovery(sources=[_Capturing()])
    svc = DiscoveryService(
        storage, disc, embedding, base, advanced_learning=advanced
    )
    svc.run_discovery(
        campaign.id, SearchCriteria(campaign_id=campaign.id, titles=("engineer",))
    )
    assert "engineer" in seen["titles"]
    assert "Site Reliability Engineer" in seen["titles"]


# === scoring bias (FR-LEARN-5) ============================================
@pytest.mark.unit
def test_scoring_leans_toward_live_converting_signature(storage, embedding, campaign):
    base = LearningService(storage, embedding)
    advanced = AdvancedLearningService(base=base, storage=storage)
    # A conversion for a python/fastapi backend role writes role:/skill: features.
    _record_live_conversion(
        storage,
        advanced,
        campaign.id,
        job_title="Backend Engineer",
        description="python fastapi postgres backend services",
    )

    crit = SearchCriteria(campaign_id=campaign.id, keywords=("engineer",))
    matching = JobPosting(
        id=JobPostingId(new_id()),
        campaign_id=campaign.id,
        title="Backend Engineer",
        company="A",
        source_url="u1",
        description="python fastapi postgres backend services",
    )
    non_matching = JobPosting(
        id=JobPostingId(new_id()),
        campaign_id=campaign.id,
        title="Frontend Designer",
        company="B",
        source_url="u2",
        description="figma css design tokens visual",
    )

    biased = ScoringService(
        storage, llm=None, embedding=embedding, learning=base, advanced_learning=advanced
    )
    # Unbiased control: same criteria, but no learning at all.
    unbiased = ScoringService(storage, llm=None, embedding=embedding)

    m_biased = biased.score_posting(matching, crit).score
    m_unbiased = unbiased.score_posting(matching, crit).score
    # The matching role is lifted beyond the bare-criteria score, and disclosed.
    assert m_biased > m_unbiased
    assert "converting-role signature" in biased.score_posting(matching, crit).rationale
    # And the matching role now outranks the non-matching one beyond bare criteria.
    assert m_biased > biased.score_posting(non_matching, crit).score


@pytest.mark.unit
def test_scoring_unchanged_with_no_conversion_history(storage, embedding, campaign):
    base = LearningService(storage, embedding)
    advanced = AdvancedLearningService(base=base, storage=storage)
    crit = SearchCriteria(campaign_id=campaign.id, keywords=("engineer",))
    posting = JobPosting(
        id=JobPostingId(new_id()),
        campaign_id=campaign.id,
        title="Backend Engineer",
        company="A",
        source_url="u1",
        description="python fastapi backend",
    )
    biased = ScoringService(
        storage, llm=None, embedding=embedding, learning=base, advanced_learning=advanced
    )
    plain = ScoringService(storage, llm=None, embedding=embedding)
    # No conversion => byte-identical score + no signature disclosure.
    assert biased.score_posting(posting, crit).score == plain.score_posting(posting, crit).score
    assert "converting-role signature" not in biased.score_posting(posting, crit).rationale


# === variant-selection bias (FR-LEARN-5) ==================================
def _add_variant(storage, cid, *, sig: str, approved=True) -> ResumeVariant:
    v = ResumeVariant(
        id=ResumeVariantId(new_id()),
        campaign_id=cid,
        storage_path=f"variants/{new_id()}.tex",
        parent_id=None,
        targeted_jd_signature=sig,
        approved=approved,
    )
    storage.resume_variants.add(v)
    storage.commit()
    return v


@pytest.mark.unit
def test_variant_tied_to_past_conversion_is_preferred(storage, embedding, campaign):
    base = LearningService(storage, embedding)
    advanced = AdvancedLearningService(base=base, storage=storage)
    # Two equally-covering approved variants (identical signature so coverage ties).
    converted = _add_variant(storage, campaign.id, sig="python,backend")
    other = _add_variant(storage, campaign.id, sig="python,backend")
    # A live conversion used the FIRST variant -> writes variant:{id} into the signature.
    _record_live_conversion(
        storage,
        advanced,
        campaign.id,
        job_title="Backend Engineer",
        resume_variant_id=converted.id,
        description="python backend",
    )

    svc = MaterialService(
        storage,
        llm=None,
        resume_tailoring=None,
        embedding=embedding,
        learning=base,
        advanced_learning=advanced,
    )
    # jd_terms cover both variants identically; the converting-variant tiebreak decides.
    jd_terms = ["python", "backend"]
    posting_id = JobPostingId(new_id())
    # Threshold high so reuse only happens on coverage; here we just inspect the choice
    # the selector makes among the two reusable variants.
    result = svc.select_or_generate(
        campaign.id, posting_id, jd_terms, "python backend", threshold=50
    )
    assert not result.generated
    assert result.variant.id == converted.id
    # Sanity: the alignment helper prefers the converted variant directly.
    align = svc._converting_alignment_for(campaign.id)
    assert align(converted) > align(other)


@pytest.mark.unit
def test_variant_selection_unchanged_with_no_history(storage, embedding, campaign):
    base = LearningService(storage, embedding)
    advanced = AdvancedLearningService(base=base, storage=storage)
    v1 = _add_variant(storage, campaign.id, sig="python,backend")
    v2 = _add_variant(storage, campaign.id, sig="python,backend")
    svc = MaterialService(
        storage,
        llm=None,
        resume_tailoring=None,
        embedding=embedding,
        learning=base,
        advanced_learning=advanced,
    )
    align = svc._converting_alignment_for(campaign.id)
    # No conversion => uniform 0.0 bias (selection falls back to coverage).
    assert align(v1) == 0.0
    assert align(v2) == 0.0


# === hard criteria still gate (FR-LEARN-5 advisory only) ===================
@pytest.mark.unit
def test_bias_never_overrides_hard_criteria_gate(storage, embedding, campaign):
    base = LearningService(storage, embedding)
    advanced = AdvancedLearningService(base=base, storage=storage)
    _record_live_conversion(
        storage,
        advanced,
        campaign.id,
        job_title="Backend Engineer",
        description="python fastapi backend",
    )
    # Criteria the user hard-set: only backend python roles are viable.
    crit = SearchCriteria(
        campaign_id=campaign.id, titles=("Backend Engineer",), keywords=("python",)
    )
    # A clearly off-criteria posting that does NOT match the converting signature
    # either. Bias must not lift it over the viability threshold.
    off = JobPosting(
        id=JobPostingId(new_id()),
        campaign_id=campaign.id,
        title="Warehouse Associate",
        company="C",
        source_url="u3",
        description="forklift pallets shipping receiving manual labor",
    )
    svc = ScoringService(
        storage,
        llm=None,
        embedding=embedding,
        learning=base,
        advanced_learning=advanced,
        threshold=70,
    )
    scoring = svc.score_posting(off, crit)
    # Advisory bias cannot rescue a role the criteria exclude.
    assert not svc.is_viable(scoring)
