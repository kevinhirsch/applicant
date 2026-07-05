"""Dark-engine audit B5 items 39 + 40: regression coverage for two engine
read-models that existed with zero callers/no router before this change.

Item 39 — "match to your past wins" explainability: ``AdvancedLearningService.
explain_text_alignment`` (a read-only companion to the already-live
``text_alignment`` scoring bias) is now reachable at
``GET /api/criteria/{campaign_id}/alignment/{posting_id}``.

Item 40 — degraded-draft flag invisible in review: ``MaterialService.
last_generation_degraded`` / the résumé-variant equivalent now reach the
existing ``documents.py`` read-models (``list_for_application`` /
``list_variants``) as ``degraded`` / ``degraded_reason``, via the existing
``provenance`` (documents) and ``fit_scores`` (résumé variants) JSON columns —
no schema migration.

Hermetic: in-memory storage, no TeX/LLM/DB. Mirrors the fixture + direct
storage-seeding style of ``tests/unit/test_promote_variant_route.py``.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from applicant.app.main import create_app
from applicant.application.services.material_service import MaterialService
from applicant.core.entities.application import Application
from applicant.core.entities.campaign import Campaign
from applicant.core.entities.generated_document import (
    DocumentType,
    GeneratedDocument,
    LearnedProvenance,
)
from applicant.core.entities.job_posting import JobPosting
from applicant.core.entities.learning_model import LearningModel
from applicant.core.entities.outcome_event import OutcomeEvent
from applicant.core.entities.resume_variant import ResumeVariant
from applicant.core.ids import (
    ApplicationId,
    CampaignId,
    GeneratedDocumentId,
    JobPostingId,
    OutcomeEventId,
    ResumeVariantId,
    new_id,
)
from applicant.core.state_machine import ApplicationState


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        # Open the LLM gate (FR-UI-5) so documents/criteria routers are reachable.
        r = c.post(
            "/api/setup/llm",
            json={"provider": "ollama", "base_url": "http://localhost:11434/v1", "model": "llama3.1"},
        )
        assert r.status_code == 204
        yield c


# === item 40: degraded cover-letter/screening-answer document ==============


def test_degraded_document_is_surfaced_and_excluded_from_what_i_drew_on(client):
    storage = client.app.state.container.storage
    cid, aid = CampaignId(new_id()), ApplicationId(new_id())
    doc = GeneratedDocument(
        id=GeneratedDocumentId(new_id()),
        campaign_id=cid,
        application_id=aid,
        type=DocumentType.COVER_LETTER,
        content="Dear hiring manager...",
        approved=False,
        provenance=(
            LearnedProvenance(kind="memory", label="Prefers concise openings", ref="m1"),
            LearnedProvenance(
                kind=MaterialService.DEGRADED_PROVENANCE_KIND,
                label="The writing model was unavailable, so this draft used a basic "
                "template instead of being tailored by AI. Review it closely before approving.",
                ref="",
            ),
        ),
    )
    storage.documents.add(doc)
    storage.commit()

    res = client.get(f"/api/documents/applications/{aid}")
    assert res.status_code == 200
    item = res.json()["items"][0]
    assert item["degraded"] is True
    assert "basic template" in item["degraded_reason"]
    # The degraded sentinel must never show up in "What I drew on" — that list
    # is for genuinely learned items only.
    kinds = {p["kind"] for p in item["provenance"]}
    assert "degraded" not in kinds
    assert "memory" in kinds  # the real learned item survives the filter


def test_real_document_is_not_flagged_degraded(client):
    storage = client.app.state.container.storage
    cid, aid = CampaignId(new_id()), ApplicationId(new_id())
    doc = GeneratedDocument(
        id=GeneratedDocumentId(new_id()),
        campaign_id=cid,
        application_id=aid,
        type=DocumentType.SCREENING_ANSWER,
        content="Eight years.",
        approved=False,
    )
    storage.documents.add(doc)
    storage.commit()

    item = client.get(f"/api/documents/applications/{aid}").json()["items"][0]
    assert item["degraded"] is False
    assert item["degraded_reason"] == ""


# === item 40: degraded résumé variant ======================================


def test_degraded_resume_variant_is_surfaced_in_the_variant_library(client):
    storage = client.app.state.container.storage
    cid = CampaignId(new_id())
    vid = ResumeVariantId(new_id())
    storage.resume_variants.add(
        ResumeVariant(
            id=vid,
            campaign_id=cid,
            storage_path="cv.tex",
            approved=False,
            fit_scores={MaterialService.DEGRADED_FIT_SCORE_KEY: True},
        )
    )
    storage.commit()

    res = client.get(f"/api/documents/variants/{cid}")
    assert res.status_code == 200
    rows = res.json()["variants"]
    assert len(rows) == 1
    assert rows[0]["degraded"] is True


def test_non_degraded_resume_variant_reports_degraded_false(client):
    storage = client.app.state.container.storage
    cid = CampaignId(new_id())
    vid = ResumeVariantId(new_id())
    storage.resume_variants.add(
        ResumeVariant(id=vid, campaign_id=cid, storage_path="cv.tex", approved=True)
    )
    storage.commit()

    rows = client.get(f"/api/documents/variants/{cid}").json()["variants"]
    assert rows[0]["degraded"] is False


# === item 39: per-posting "match to your past wins" alignment ==============


def _seed_campaign(storage, cid):
    """``LearningService.persist_model``/``load_model`` key off a real campaign
    row (``campaign.learning_state``), so a conversion fold silently no-ops
    without one."""
    storage.campaigns.add(Campaign(id=cid, name="c"))
    storage.commit()


def _seed_posting(storage, cid, *, title="Senior Backend Engineer", description=""):
    posting = JobPosting(
        id=JobPostingId(new_id()),
        campaign_id=cid,
        title=title,
        company="Acme",
        source_url="https://example.test/job",
        description=description,
    )
    storage.postings.add(posting)
    storage.commit()
    return posting


def test_alignment_404_for_unknown_posting(client):
    cid = CampaignId(new_id())
    res = client.get(f"/api/criteria/{cid}/alignment/no-such-posting")
    assert res.status_code == 404


def test_alignment_404_when_posting_belongs_to_a_different_campaign(client):
    storage = client.app.state.container.storage
    other_cid = CampaignId(new_id())
    posting = _seed_posting(storage, other_cid)
    res = client.get(f"/api/criteria/{new_id()}/alignment/{posting.id}")
    assert res.status_code == 404


def test_alignment_cold_start_before_any_conversion(client):
    storage = client.app.state.container.storage
    cid = CampaignId(new_id())
    posting = _seed_posting(storage, cid, title="Senior Backend Engineer")

    res = client.get(f"/api/criteria/{cid}/alignment/{posting.id}")
    assert res.status_code == 200
    body = res.json()
    assert body["campaign_id"] == cid
    assert body["posting_id"] == posting.id
    assert body["cold_start"] is True
    assert body["score"] == 0.0
    assert body["matched"] == []


def test_alignment_reports_matched_evidence_after_a_conversion(client):
    container = client.app.state.container
    storage = container.storage
    cid = CampaignId(new_id())
    _seed_campaign(storage, cid)

    # Record a real conversion (approval + submission) for a senior backend role
    # so the campaign's converting-role signature is non-empty.
    converted_app = Application(
        id=ApplicationId(new_id()),
        campaign_id=cid,
        posting_id=JobPostingId(new_id()),
        status=ApplicationState.APPROVED,
        role_name="Senior Backend Engineer",
        work_mode="remote",
    )
    event = OutcomeEvent(id=OutcomeEventId(new_id()), application_id=converted_app.id, type="submitted")
    model = container.advanced_learning_service.record_conversion(
        LearningModel(campaign_id=cid), converted_app, [event]
    )
    container.learning_service.persist_model(model)

    # A new candidate posting that reads like the role that converted.
    posting = _seed_posting(
        storage, cid,
        title="Senior Backend Engineer",
        description="Fully remote backend role.",
    )

    res = client.get(f"/api/criteria/{cid}/alignment/{posting.id}")
    assert res.status_code == 200
    body = res.json()
    assert body["cold_start"] is False
    assert body["score"] > 0.0
    facets = {m["facet"] for m in body["matched"]}
    assert "role" in facets


def test_alignment_unrelated_posting_scores_zero_but_not_cold_start(client):
    container = client.app.state.container
    storage = container.storage
    cid = CampaignId(new_id())
    _seed_campaign(storage, cid)

    converted_app = Application(
        id=ApplicationId(new_id()),
        campaign_id=cid,
        posting_id=JobPostingId(new_id()),
        status=ApplicationState.APPROVED,
        role_name="Senior Backend Engineer",
        work_mode="remote",
    )
    event = OutcomeEvent(id=OutcomeEventId(new_id()), application_id=converted_app.id, type="submitted")
    model = container.advanced_learning_service.record_conversion(
        LearningModel(campaign_id=cid), converted_app, [event]
    )
    container.learning_service.persist_model(model)

    posting = _seed_posting(storage, cid, title="Pastry Chef", description="Onsite bakery role.")

    body = client.get(f"/api/criteria/{cid}/alignment/{posting.id}").json()
    assert body["cold_start"] is False
    assert body["score"] == 0.0
    assert body["matched"] == []
