"""P1-8 — Résumé <-> JD keyword / ATS match score (road-to-market backlog).

Engine half of the story, two behaviors:

* ``MaterialService.select_or_generate`` PERSISTS the deterministic keyword-
  coverage check (coverage + missing terms + the posting it was scored against)
  into the variant's existing free-form ``fit_scores`` JSON dict — on BOTH the
  reuse path and the freshly-generated path — so the review surface / variant
  library renders a real stored "covers N%; missing: ..." line instead of
  "not scored". Existing ``fit_scores`` keys (e.g. the degraded-draft flag)
  survive the merge.
* ``DigestService`` digest rows carry a deterministic ``keyword_coverage`` /
  ``keyword_matched`` / ``keyword_missing`` computed via the SAME pure
  ``core.rules.jd_match`` scorer the redline review uses, against the
  candidate's own base résumé + attribute-cloud text — and HONESTLY omit the
  fields when no résumé/profile text is on file (absence of a check must never
  render as a check, H-series).
"""

from __future__ import annotations

import pytest

from applicant.adapters.embedding.local_embedding import LocalEmbedding
from applicant.adapters.resume_tailoring.latex_tailor import LatexTailor
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.digest_service import DigestService
from applicant.application.services.material_service import MaterialService
from applicant.core.entities.attribute import Attribute
from applicant.core.entities.job_posting import JobPosting
from applicant.core.entities.onboarding_profile import OnboardingProfile
from applicant.core.entities.resume_variant import ResumeVariant
from applicant.core.ids import (
    AttributeId,
    CampaignId,
    JobPostingId,
    OnboardingProfileId,
    ResumeVariantId,
    new_id,
)

BASE = (
    "\\section{Skills}\n"
    "Python developer who built data pipelines.\n"
    "Wrote SQL for analytics dashboards.\n"
)


@pytest.fixture
def storage() -> InMemoryStorage:
    return InMemoryStorage()


@pytest.fixture
def svc(storage) -> MaterialService:
    return MaterialService(
        storage, llm=None, resume_tailoring=LatexTailor(), embedding=LocalEmbedding()
    )


def _add_variant(storage, cid, *, approved=True, sig="Python", fit_scores=None) -> ResumeVariant:
    v = ResumeVariant(
        id=ResumeVariantId(new_id()),
        campaign_id=cid,
        storage_path=f"variants/{new_id()}.tex",
        targeted_jd_signature=sig,
        approved=approved,
        fit_scores=dict(fit_scores or {}),
    )
    storage.resume_variants.add(v)
    storage.commit()
    return v


# === MaterialService: coverage persisted in fit_scores =====================


@pytest.mark.unit
def test_generated_variant_persists_coverage_and_missing_terms(svc, storage):
    cid = CampaignId(new_id())
    pid = JobPostingId(new_id())
    sel = svc.select_or_generate(cid, pid, ["Python", "Kubernetes", "Terraform"], BASE)
    assert sel.generated is True
    stored = storage.resume_variants.get(sel.variant.id)
    assert stored.fit_scores["coverage"] == pytest.approx(sel.fit.coverage)
    assert stored.fit_scores["posting_id"] == str(pid)
    # The JD terms the generated body does not cover are stored, verbatim.
    assert set(stored.fit_scores["missing_terms"]) == set(sel.fit.missing_terms)
    assert "Kubernetes" in stored.fit_scores["missing_terms"]


@pytest.mark.unit
def test_reused_variant_banks_the_coverage_check_too(svc, storage):
    cid = CampaignId(new_id())
    pid = JobPostingId(new_id())
    v = _add_variant(storage, cid, sig="Python,SQL")
    sel = svc.select_or_generate(cid, pid, ["Python", "SQL"], BASE)
    assert sel.generated is False
    stored = storage.resume_variants.get(v.id)
    assert stored.fit_scores["coverage"] == pytest.approx(1.0)
    assert stored.fit_scores["missing_terms"] == []
    assert stored.fit_scores["posting_id"] == str(pid)


@pytest.mark.unit
def test_coverage_merge_preserves_existing_fit_score_keys(svc, storage):
    """The degraded-draft flag (audit #40) rides the same dict — it must survive."""
    cid = CampaignId(new_id())
    v = _add_variant(
        storage,
        cid,
        sig="Python,SQL",
        fit_scores={MaterialService.DEGRADED_FIT_SCORE_KEY: True},
    )
    sel = svc.select_or_generate(cid, JobPostingId(new_id()), ["Python", "SQL"], BASE)
    assert sel.generated is False
    stored = storage.resume_variants.get(v.id)
    assert stored.fit_scores[MaterialService.DEGRADED_FIT_SCORE_KEY] is True
    assert stored.fit_scores["coverage"] == pytest.approx(1.0)


# === DigestService: keyword-coverage on digest rows ========================


class _ViableScoring:
    def score_posting(self, posting, criteria=None):
        from applicant.core.entities.viability_scoring import ViabilityScoring

        return ViabilityScoring(posting_id=posting.id, score=0.9, rationale="fit")

    def is_viable(self, scoring):
        return True


class _NullNotifier:
    def notify(self, n):
        return "h"

    def expire(self, k):
        pass


def _seed_posting(storage, cid, *, description) -> JobPosting:
    posting = JobPosting(
        id=JobPostingId(new_id()),
        campaign_id=cid,
        title="Platform Engineer",
        company="Acme",
        source_url="https://example.com/job",
        description=description,
    )
    storage.postings.add(posting)
    storage.commit()
    return posting


def _seed_profile(storage, cid, resume_text: str) -> None:
    storage.onboarding_profiles.add(
        OnboardingProfile(
            id=OnboardingProfileId(new_id()),
            campaign_id=cid,
            intake={"base_resume": {"raw_text": resume_text}},
        )
    )
    storage.commit()


@pytest.mark.unit
def test_digest_row_carries_deterministic_keyword_coverage():
    storage = InMemoryStorage()
    cid = CampaignId(new_id())
    _seed_profile(storage, cid, "Python developer. Built AWS data pipelines with SQL.")
    _seed_posting(
        storage,
        cid,
        description="We need Python and AWS experience; Kubernetes is required.",
    )
    digest = DigestService(storage, _NullNotifier(), _ViableScoring())
    rows = digest.build_digest(cid)
    assert len(rows) == 1
    row = rows[0]
    assert isinstance(row["keyword_coverage"], int)
    assert 0 <= row["keyword_coverage"] <= 100
    assert "Python" in row["keyword_matched"]
    assert "AWS" in row["keyword_matched"]
    assert "Kubernetes" in row["keyword_missing"]


@pytest.mark.unit
def test_digest_row_attribute_cloud_counts_toward_coverage():
    """Profile attributes are part of the candidate's truth, not just the résumé."""
    storage = InMemoryStorage()
    cid = CampaignId(new_id())
    _seed_profile(storage, cid, "Python developer.")
    storage.attributes.add(
        Attribute(id=AttributeId(new_id()), campaign_id=cid, name="skill", value="Kubernetes")
    )
    storage.commit()
    _seed_posting(storage, cid, description="Python plus Kubernetes required.")
    digest = DigestService(storage, _NullNotifier(), _ViableScoring())
    row = digest.build_digest(cid)[0]
    assert "Kubernetes" in row["keyword_matched"]
    assert "Kubernetes" not in row["keyword_missing"]


@pytest.mark.unit
def test_digest_row_omits_coverage_when_no_resume_on_file():
    """Honesty (H-series): no profile text means NO chip — never a fabricated 0%."""
    storage = InMemoryStorage()
    cid = CampaignId(new_id())
    _seed_posting(storage, cid, description="Python and Kubernetes required.")
    digest = DigestService(storage, _NullNotifier(), _ViableScoring())
    row = digest.build_digest(cid)[0]
    assert "keyword_coverage" not in row
    assert "keyword_missing" not in row
