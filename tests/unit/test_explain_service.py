"""ExplainService — EXPLAIN backend: weighted greens/reds breakdown (unit lane).

Covers: deterministic weighting reconciles with the persisted score, the
no-LLM degrade path (offline/token parity), the optional LLM nuance pass, the
``to_payload``/``compact`` serializers, and the lazy-compute-and-cache /
cache-invalidation logic used by the ``GET /api/explain/{id}`` endpoint.
"""

from __future__ import annotations

import pytest

from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.explain_service import ExplainService
from applicant.core.entities.job_posting import JobPosting
from applicant.core.entities.search_criteria import SearchCriteria
from applicant.core.entities.viability_scoring import ViabilityScoring
from applicant.core.ids import CampaignId, JobPostingId, new_id
from applicant.ports.driven.llm import LLMResult


def _posting(**overrides) -> JobPosting:
    cid = overrides.pop("campaign_id", CampaignId(new_id()))
    defaults = dict(
        id=JobPostingId(new_id()),
        campaign_id=cid,
        title="Scrum Master",
        company="Acme",
        source_url="https://job-boards.greenhouse.io/acme/jobs/123",
        description="We are hiring a Scrum Master to run Agile ceremonies.",
    )
    defaults.update(overrides)
    return JobPosting(**defaults)


def _criteria(cid: CampaignId, **overrides) -> SearchCriteria:
    defaults = dict(
        campaign_id=cid,
        titles=("Scrum Master",),
        keywords=("Agile", "Scrum", "Kanban"),
        human_readable="Agile delivery leader",
    )
    defaults.update(overrides)
    return SearchCriteria(**defaults)


class _FakeLLM:
    def __init__(self, *, configured=True, text="A great domain-fit match.", raises=False):
        self._configured = configured
        self._text = text
        self._raises = raises
        self.calls = 0

    def is_configured(self) -> bool:
        return self._configured

    def complete(self, messages, *, start_tier=1, json_schema=None, max_tokens=None):
        self.calls += 1
        if self._raises:
            raise RuntimeError("boom")
        return LLMResult(text=self._text, tier=1, model="fake")


@pytest.mark.unit
class TestDeterministicBreakdown:
    def test_no_llm_produces_complete_breakdown(self):
        """Deterministic-first: with llm=None the breakdown is still full and sane."""
        svc = ExplainService(InMemoryStorage(), llm=None, embedding=None)
        posting = _posting()
        criteria = _criteria(posting.campaign_id)
        viability = ViabilityScoring(posting_id=posting.id, score=0.8)

        breakdown = svc.build_breakdown(posting, criteria, viability)

        assert breakdown.posting_id == posting.id
        assert breakdown.score == pytest.approx(0.8)
        assert breakdown.factors
        assert all(f.source == "deterministic" for f in breakdown.factors)
        assert breakdown.summary

    def test_llm_configured_but_not_called_does_not_crash(self):
        """An llm object with is_configured()==False is never invoked."""
        llm = _FakeLLM(configured=False)
        svc = ExplainService(InMemoryStorage(), llm=llm, embedding=None)
        posting = _posting()
        svc.build_breakdown(posting, _criteria(posting.campaign_id))
        assert llm.calls == 0

    @pytest.mark.parametrize("target", [0.05, 0.35, 0.6, 0.91, 1.0])
    def test_contributions_reconcile_with_persisted_score(self, target):
        """The sum of every factor's contribution equals the reconciled score
        (0..100 scale) regardless of what the deterministic factors compute on
        their own — the reconciliation factor absorbs the gap."""
        svc = ExplainService(InMemoryStorage(), llm=None, embedding=None)
        posting = _posting()
        criteria = _criteria(posting.campaign_id)
        viability = ViabilityScoring(posting_id=posting.id, score=target)

        breakdown = svc.build_breakdown(posting, criteria, viability)

        total = sum(f.contribution for f in breakdown.factors)
        assert total == pytest.approx(round(target * 100, 2), abs=0.05)

    def test_non_posting_gate_flags_red(self):
        """A known non-job-board domain (posting_quality) flags red with a reason."""
        svc = ExplainService(InMemoryStorage(), llm=None, embedding=None)
        posting = _posting(
            title="Scrum Master vs Release Train Engineer",
            source_url="https://reddit.com/r/agile/comparison",
            description="",
        )
        breakdown = svc.build_breakdown(posting, _criteria(posting.campaign_id))

        quality_factor = next(
            f for f in breakdown.factors if f.label == "Real, specific job posting"
        )
        assert quality_factor.polarity == "red"
        assert quality_factor.detail  # a plain-language reason is present

    def test_real_posting_flags_green(self):
        svc = ExplainService(InMemoryStorage(), llm=None, embedding=None)
        posting = _posting()
        breakdown = svc.build_breakdown(posting, _criteria(posting.campaign_id))
        quality_factor = next(
            f for f in breakdown.factors if f.label == "Real, specific job posting"
        )
        assert quality_factor.polarity == "green"

    def test_no_criteria_jd_match_is_neutral(self):
        """No search criteria set -> the keyword-overlap factor is neutral, not red."""
        svc = ExplainService(InMemoryStorage(), llm=None, embedding=None)
        posting = _posting()
        breakdown = svc.build_breakdown(posting, criteria=None)
        jd_factor = next(
            f
            for f in breakdown.factors
            if f.label == "Skill & keyword overlap with your stated criteria"
        )
        assert jd_factor.polarity == "neutral"
        assert "no search criteria" in jd_factor.detail.lower()

    def test_freshness_omitted_when_no_dates_known(self):
        svc = ExplainService(InMemoryStorage(), llm=None, embedding=None)
        posting = _posting(date_posted=None, first_seen=None)
        breakdown = svc.build_breakdown(posting, _criteria(posting.campaign_id))
        assert not any(f.label == "Posting freshness" for f in breakdown.factors)

    def test_freshness_flags_stale(self):
        from datetime import UTC, datetime, timedelta

        svc = ExplainService(InMemoryStorage(), llm=None, embedding=None)
        old = datetime.now(UTC) - timedelta(days=45)
        posting = _posting(date_posted=old)
        breakdown = svc.build_breakdown(posting, _criteria(posting.campaign_id))
        fresh_factor = next(f for f in breakdown.factors if f.label == "Posting freshness")
        assert fresh_factor.polarity == "red"
        assert "stale" in fresh_factor.detail.lower()

    def test_ats_match_factor_absent_by_default(self):
        svc = ExplainService(InMemoryStorage(), llm=None, embedding=None)
        posting = _posting()
        breakdown = svc.build_breakdown(posting, _criteria(posting.campaign_id))
        assert not any(f.label == "Form pre-fill match rate" for f in breakdown.factors)

    def test_ats_match_factor_present_when_prefill_data_recorded(self):
        svc = ExplainService(InMemoryStorage(), llm=None, embedding=None)
        posting = _posting(rationale={"prefill_match": {"filled": 1, "detected": 10}})
        breakdown = svc.build_breakdown(posting, _criteria(posting.campaign_id))
        ats_factor = next(f for f in breakdown.factors if f.label == "Form pre-fill match rate")
        assert ats_factor.polarity == "red"  # 1/10 = 0.1, below the default 0.2 floor
        assert "wrong-ats" in ats_factor.detail.lower()

    def test_falls_back_to_persisted_viability_score_when_none_passed(self):
        svc = ExplainService(InMemoryStorage(), llm=None, embedding=None)
        posting = _posting(viability_score=0.42)
        breakdown = svc.build_breakdown(posting, _criteria(posting.campaign_id))
        assert breakdown.score == pytest.approx(0.42)

    def test_falls_back_to_own_weighted_average_when_no_score_anywhere(self):
        svc = ExplainService(InMemoryStorage(), llm=None, embedding=None)
        posting = _posting()  # viability_score defaults to None
        breakdown = svc.build_breakdown(posting, _criteria(posting.campaign_id))
        assert 0.0 <= breakdown.score <= 1.0


@pytest.mark.unit
class TestLlmNuance:
    def test_nuance_factor_added_when_llm_configured(self):
        llm = _FakeLLM(text="Strong domain fit drove this score.")
        svc = ExplainService(InMemoryStorage(), llm=llm, embedding=None)
        posting = _posting()
        breakdown = svc.build_breakdown(
            posting, _criteria(posting.campaign_id), ViabilityScoring(posting.id, 0.8)
        )
        nuance = [f for f in breakdown.factors if f.source == "llm"]
        assert len(nuance) == 1
        assert nuance[0].weight == 0.0
        assert nuance[0].contribution == 0.0
        assert nuance[0].polarity == "neutral"
        assert "domain fit" in nuance[0].detail

    def test_nuance_never_changes_score_reconciliation(self):
        """Adding the LLM nuance factor must not perturb the reconciliation."""
        llm = _FakeLLM(text="Some narrative.")
        svc = ExplainService(InMemoryStorage(), llm=llm, embedding=None)
        posting = _posting()
        viability = ViabilityScoring(posting.id, 0.63)
        breakdown = svc.build_breakdown(posting, _criteria(posting.campaign_id), viability)
        total = sum(f.contribution for f in breakdown.factors)
        assert total == pytest.approx(63.0, abs=0.05)

    def test_nuance_failure_degrades_silently(self):
        llm = _FakeLLM(raises=True)
        svc = ExplainService(InMemoryStorage(), llm=llm, embedding=None)
        posting = _posting()
        breakdown = svc.build_breakdown(posting, _criteria(posting.campaign_id))
        assert not any(f.source == "llm" for f in breakdown.factors)


@pytest.mark.unit
class TestSerializers:
    def test_to_payload_shape(self):
        svc = ExplainService(InMemoryStorage(), llm=None, embedding=None)
        posting = _posting()
        breakdown = svc.build_breakdown(
            posting, _criteria(posting.campaign_id), ViabilityScoring(posting.id, 0.77)
        )
        payload = svc.to_payload(breakdown)
        assert payload["posting_id"] == str(posting.id)
        assert payload["score"] == pytest.approx(0.77)
        assert payload["score_pct"] == 77
        assert isinstance(payload["summary"], str) and payload["summary"]
        assert isinstance(payload["factors"], list) and payload["factors"]
        factor = payload["factors"][0]
        assert set(factor) == {"label", "polarity", "weight", "contribution", "source", "detail"}

    def test_compact_returns_top_n_chips_by_magnitude(self):
        svc = ExplainService(InMemoryStorage(), llm=None, embedding=None)
        posting = _posting()
        breakdown = svc.build_breakdown(
            posting, _criteria(posting.campaign_id), ViabilityScoring(posting.id, 0.9)
        )
        chip_view = svc.compact(breakdown, top_n=2)
        assert len(chip_view["chips"]) <= 2
        contributions = [abs(c["contribution"]) for c in chip_view["chips"]]
        assert contributions == sorted(contributions, reverse=True)
        assert chip_view["score_pct"] == 90
        assert chip_view["summary"] == breakdown.summary


@pytest.mark.unit
class TestPersistenceAndLazyCache:
    def test_persist_breakdown_merges_without_clobbering_other_rationale_keys(self):
        storage = InMemoryStorage()
        svc = ExplainService(storage, llm=None, embedding=None)
        posting = _posting(rationale={"text": "existing rationale", "viable": True})
        storage.postings.add(posting)
        storage.commit()

        breakdown = svc.build_breakdown(posting, _criteria(posting.campaign_id))
        updated = svc.persist_breakdown(posting, breakdown)

        assert updated.rationale["text"] == "existing rationale"
        assert updated.rationale["viable"] is True
        assert "breakdown" in updated.rationale
        assert updated.rationale["breakdown"]["score"] == pytest.approx(breakdown.score)

    def test_explain_posting_lazily_computes_and_caches(self):
        storage = InMemoryStorage()
        svc = ExplainService(storage, llm=None, embedding=None)
        posting = _posting(viability_score=0.55)
        storage.postings.add(posting)
        storage.commit()

        breakdown = svc.explain_posting(posting.id)
        assert breakdown is not None
        assert breakdown.score == pytest.approx(0.55)

        stored = storage.postings.get(posting.id)
        assert "breakdown" in stored.rationale
        assert stored.rationale["breakdown"]["score"] == pytest.approx(0.55)

    def test_explain_posting_reuses_cache_when_score_unchanged(self):
        storage = InMemoryStorage()
        svc = ExplainService(storage, llm=None, embedding=None)
        posting = _posting(viability_score=0.55)
        storage.postings.add(posting)
        storage.commit()

        first = svc.explain_posting(posting.id)
        second = svc.explain_posting(posting.id)
        assert first.summary == second.summary
        assert first.score == pytest.approx(second.score)

    def test_explain_posting_endpoint_path_never_calls_the_llm(self):
        """Regression: a wedged model tier once timed the GET /api/explain proxy
        out at 10s because the lazy-compute path called ``llm.complete``
        synchronously and the try/except swallows LLM *errors* but not a *hang*.
        The endpoint path must be deterministic-only — the nuance is a
        background-trigger enrichment (see ``build_breakdown(with_nuance=...)``)."""
        storage = InMemoryStorage()
        llm = _FakeLLM(text="must never be reached on the endpoint path")
        svc = ExplainService(storage, llm=llm, embedding=None)
        posting = _posting(viability_score=0.55)
        storage.postings.add(posting)
        storage.commit()

        breakdown = svc.explain_posting(posting.id)

        assert llm.calls == 0  # the user-facing path never blocks on the LLM
        assert breakdown is not None
        assert not any(f.source == "llm" for f in breakdown.factors)
        assert breakdown.summary  # still a complete, useful breakdown

    def test_build_breakdown_with_nuance_false_skips_the_llm(self):
        llm = _FakeLLM(text="skipped")
        svc = ExplainService(InMemoryStorage(), llm=llm, embedding=None)
        posting = _posting()
        breakdown = svc.build_breakdown(
            posting, _criteria(posting.campaign_id), with_nuance=False
        )
        assert llm.calls == 0
        assert not any(f.source == "llm" for f in breakdown.factors)

    def test_build_breakdown_default_still_includes_nuance_for_the_trigger_path(self):
        """The background ViabilityScored trigger keeps the prose enrichment."""
        llm = _FakeLLM(text="Strong domain fit drove this score.")
        svc = ExplainService(InMemoryStorage(), llm=llm, embedding=None)
        posting = _posting()
        breakdown = svc.build_breakdown(
            posting, _criteria(posting.campaign_id), ViabilityScoring(posting.id, 0.8)
        )
        assert llm.calls == 1
        assert any(f.source == "llm" for f in breakdown.factors)

    def test_explain_posting_invalidates_cache_on_rescore(self):
        storage = InMemoryStorage()
        svc = ExplainService(storage, llm=None, embedding=None)
        posting = _posting(viability_score=0.30)
        storage.postings.add(posting)
        storage.commit()

        svc.explain_posting(posting.id)  # caches at 0.30

        import dataclasses

        rescored = dataclasses.replace(storage.postings.get(posting.id), viability_score=0.85)
        storage.postings.add(rescored)
        storage.commit()

        breakdown = svc.explain_posting(posting.id)
        assert breakdown.score == pytest.approx(0.85)

    def test_explain_posting_missing_returns_none(self):
        storage = InMemoryStorage()
        svc = ExplainService(storage, llm=None, embedding=None)
        assert svc.explain_posting(JobPostingId("nope")) is None
