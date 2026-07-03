"""Regression: GET /api/feedback/{campaign_id} (dark-engine audit item 23).

``FeedbackSummaryProvider`` (``application/services/feedback_history.py``) already
walked per-application feedback -- digest decline-with-feedback reasons (FR-DIG-5)
and résumé/answer revision instructions (FR-RESUME-8) -- to feed the scheduled
curation nudge, but nothing routed that read-model to the front door: feedback was
write-only (``/freetext``, ``/survey`` only fold IN). This test mounts just the
feedback router (hermetic: ``InMemoryStorage``, no DB) and drives the new
``GET /{campaign_id}`` endpoint end-to-end, confirming it reuses the SAME provider
walk the curation nudge already exercises (mirrors
``tests/unit/test_feedback_history_curation.py``'s fixtures) rather than
re-deriving it.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.app.deps import get_storage, require_llm_configured
from applicant.app.routers.feedback import router as feedback_router
from applicant.core.entities.application import Application
from applicant.core.entities.campaign import Campaign
from applicant.core.entities.decision import Decision, DecisionType
from applicant.core.entities.generated_document import DocumentType, GeneratedDocument
from applicant.core.entities.revision_session import (
    RevisionSession,
    RevisionStatus,
    RevisionTurn,
)
from applicant.core.ids import (
    ApplicationId,
    CampaignId,
    DecisionId,
    GeneratedDocumentId,
    JobPostingId,
    RevisionSessionId,
    new_id,
)
from applicant.core.state_machine import ApplicationState


def _build_app(storage: InMemoryStorage) -> FastAPI:
    app = FastAPI()

    def _get_storage():
        return storage

    app.dependency_overrides[get_storage] = _get_storage
    app.dependency_overrides[require_llm_configured] = lambda: None
    app.include_router(feedback_router)
    return app


def _seed_app(storage, *, active=True) -> tuple[CampaignId, Application]:
    cid = CampaignId(new_id())
    storage.campaigns.add(Campaign(id=cid, name="Search", active=active))
    app = Application(
        id=ApplicationId(new_id()),
        campaign_id=cid,
        posting_id=JobPostingId(new_id()),
        status=ApplicationState.SCORED,
        role_name="Backend Engineer",
        job_title="Backend Engineer",
        work_mode="remote",
        root_url="https://acme.myworkdayjobs.com/job/9",
    )
    storage.applications.add(app)
    return cid, app


def _seed_decline(storage, app, text: str) -> None:
    storage.decisions.add(
        Decision(
            id=DecisionId(new_id()),
            application_id=app.id,
            type=DecisionType.DECLINE,
            feedback_text=text,
        )
    )


def _seed_revision(storage, app, cid, *instructions: str) -> None:
    doc = GeneratedDocument(
        id=GeneratedDocumentId(new_id()),
        campaign_id=cid,
        application_id=app.id,
        type=DocumentType.RESUME,
    )
    storage.documents.add(doc)
    storage.revisions.add(
        RevisionSession(
            id=RevisionSessionId(new_id()),
            material_id=doc.id,
            status=RevisionStatus.OPEN,
            turns=tuple(RevisionTurn(kind="free_text", instruction=i) for i in instructions),
        )
    )


@pytest.mark.unit
def test_feedback_history_route_returns_decline_and_revision_items():
    storage = InMemoryStorage()
    cid, app = _seed_app(storage)
    _seed_decline(storage, app, "Too much travel — I only want fully remote roles.")
    _seed_revision(storage, app, cid, "Drop the buzzwords from the summary.")

    client = TestClient(_build_app(storage))
    resp = client.get(f"/api/feedback/{cid}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["campaign_id"] == str(cid)
    assert len(body["items"]) == 2
    kinds = {item["kind"] for item in body["items"]}
    assert kinds == {"decline", "revision"}
    texts = " ".join(item["text"] for item in body["items"])
    assert "fully remote" in texts
    assert "buzzwords" in texts


@pytest.mark.unit
def test_feedback_history_route_empty_when_nothing_recorded():
    storage = InMemoryStorage()
    cid, _app = _seed_app(storage)

    client = TestClient(_build_app(storage))
    resp = client.get(f"/api/feedback/{cid}")

    assert resp.status_code == 200
    assert resp.json() == {"campaign_id": str(cid), "items": []}


@pytest.mark.unit
def test_feedback_history_route_scopes_to_the_requested_campaign():
    storage = InMemoryStorage()
    cid_a, app_a = _seed_app(storage)
    _cid_b, app_b = _seed_app(storage)
    _seed_decline(storage, app_a, "Campaign A reason")
    _seed_decline(storage, app_b, "Campaign B reason")

    client = TestClient(_build_app(storage))
    resp = client.get(f"/api/feedback/{cid_a}")

    body = resp.json()
    assert len(body["items"]) == 1
    assert "Campaign A reason" in body["items"][0]["text"]


@pytest.mark.unit
def test_feedback_history_route_ignores_declines_with_no_stated_reason():
    """An APPROVE / blank-feedback decision carries no lesson -- matches the
    provider's own behaviour (test_feedback_history_curation.py)."""
    storage = InMemoryStorage()
    cid, app = _seed_app(storage)
    storage.decisions.add(
        Decision(
            id=DecisionId(new_id()),
            application_id=app.id,
            type=DecisionType.APPROVE,
            feedback_text="",
        )
    )

    client = TestClient(_build_app(storage))
    resp = client.get(f"/api/feedback/{cid}")

    assert resp.json() == {"campaign_id": str(cid), "items": []}


@pytest.mark.unit
def test_feedback_history_route_does_not_shadow_index_or_writes():
    """Route-ordering regression: the new GET /{campaign_id} must not shadow the
    existing GET "" index route."""
    storage = InMemoryStorage()
    client = TestClient(_build_app(storage))

    resp = client.get("/api/feedback")
    assert resp.status_code == 200
    assert resp.json()["surface"] == "feedback"
