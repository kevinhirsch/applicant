"""Regression: POST /api/feedback/{campaign_id}/ingest (FR-LEARN-4, dark-engine
audit item 42).

`FeedbackService.ingest_parsed_input`'s list path (`AdvancedLearningService.
reconcile_inputs`) already had unit coverage (test_learning_advanced.py,
test_bugsweep2_learning_folds.py), but nothing routed it through the front door —
`applicant/app/routers/feedback.py` only exposed `/freetext` and `/survey`. This
test mounts just the feedback router (hermetic: InMemoryStorage, no DB) and drives
the new `/ingest` endpoint end-to-end, matching the shape the workspace proxy relies
on: `{applied, pending, conflicts, skipped}`.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from applicant.adapters.embedding.local_embedding import LocalEmbedding
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.app.deps import get_feedback_service, require_llm_configured
from applicant.app.routers.feedback import router as feedback_router
from applicant.application.services.feedback_service import FeedbackService
from applicant.application.services.learning_advanced import AdvancedLearningService
from applicant.application.services.learning_service import LearningService
from applicant.core.entities.attribute import Attribute
from applicant.core.entities.campaign import Campaign
from applicant.core.ids import AttributeId, CampaignId, new_id


@pytest.fixture
def storage() -> InMemoryStorage:
    return InMemoryStorage()


@pytest.fixture
def campaign(storage) -> Campaign:
    c = Campaign(id=CampaignId(new_id()), name="Test campaign")
    storage.campaigns.add(c)
    storage.commit()
    return c


def _build_app(storage: InMemoryStorage) -> FastAPI:
    learning = LearningService(storage, LocalEmbedding())
    advanced = AdvancedLearningService(base=learning, storage=storage)
    feedback = FeedbackService(storage, learning, advanced_learning=advanced)

    app = FastAPI()

    def _get_feedback_service():
        return feedback

    app.dependency_overrides[get_feedback_service] = _get_feedback_service
    app.dependency_overrides[require_llm_configured] = lambda: None
    app.include_router(feedback_router)
    return app


@pytest.mark.unit
def test_ingest_route_auto_applies_non_integral(storage, campaign):
    app = _build_app(storage)
    client = TestClient(app)

    resp = client.post(
        f"/api/feedback/{campaign.id}/ingest",
        json={"observations": [{"name": "github", "value": "octocat", "source": "chat"}]},
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["applied"] == ["github"]
    assert body["pending"] == []
    assert body["conflicts"] == []
    assert body["skipped"] == []
    names = {a.name for a in storage.attributes.list_for_campaign(campaign.id)}
    assert "github" in names


@pytest.mark.unit
def test_ingest_route_holds_integral_for_confirmation(storage, campaign):
    storage.attributes.add(
        Attribute(
            id=AttributeId(new_id()),
            campaign_id=campaign.id,
            name="legal_name",
            value="Jane Q.",
            is_integral=True,
        )
    )
    storage.commit()
    app = _build_app(storage)
    client = TestClient(app)

    resp = client.post(
        f"/api/feedback/{campaign.id}/ingest",
        json={
            "observations": [
                {"name": "legal_name", "value": "Jane Quinn", "is_integral": True, "source": "chat"}
            ]
        },
    )

    assert resp.status_code == 201
    body = resp.json()
    # An existing integral value with a NEW proposed value surfaces as a conflict
    # (never silently overwritten) rather than a bare pending hold.
    assert body["applied"] == []
    assert body["conflicts"] and body["conflicts"][0]["name"] == "legal_name"
    assert body["conflicts"][0]["current_value"] == "Jane Q."
    # Unchanged in the cloud — the paste never overwrote the held value.
    stored = next(a for a in storage.attributes.list_for_campaign(campaign.id) if a.name == "legal_name")
    assert stored.value == "Jane Q."


@pytest.mark.unit
def test_ingest_route_skips_sensitive_eeo_fields(storage, campaign):
    app = _build_app(storage)
    client = TestClient(app)

    resp = client.post(
        f"/api/feedback/{campaign.id}/ingest",
        json={"observations": [{"name": "Gender", "value": "Female", "source": "paste"}]},
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["applied"] == []
    assert "Gender" in body["skipped"]
    assert not storage.attributes.list_for_campaign(campaign.id)


@pytest.mark.unit
def test_ingest_route_batches_mixed_outcomes_in_one_call(storage, campaign):
    """The whole point of the bulk path: one paste, several outcomes at once."""
    app = _build_app(storage)
    client = TestClient(app)

    resp = client.post(
        f"/api/feedback/{campaign.id}/ingest",
        json={
            "observations": [
                {"name": "location", "value": "Austin, TX", "source": "paste"},
                {"name": "Race", "value": "Prefer not to say", "source": "paste"},
                {"name": "years_python", "value": "8", "source": "paste"},
            ]
        },
    )

    assert resp.status_code == 201
    body = resp.json()
    assert sorted(body["applied"]) == ["location", "years_python"]
    assert body["skipped"] == ["Race"]


@pytest.mark.unit
def test_ingest_route_empty_batch_is_a_no_op(storage, campaign):
    app = _build_app(storage)
    client = TestClient(app)

    resp = client.post(f"/api/feedback/{campaign.id}/ingest", json={"observations": []})

    assert resp.status_code == 201
    body = resp.json()
    assert body == {"applied": [], "pending": [], "conflicts": [], "skipped": []}
