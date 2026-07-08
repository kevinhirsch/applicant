"""Coverage: digest ROUTER (src/applicant/app/routers/digest.py).

Drives the digest surface over HTTP (hermetic: in-memory storage, capturing notifier):
the index, the automated-work-gated build/deliver/email (empty-day digest is fine), the
web-presence pre-empt signal, and the approve / decline-with-feedback decision paths
including the mandatory-feedback 422. Asserts the LLM gate AND the automated-work gate the
router declares.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from applicant.app.main import create_app
from tests.conftest import open_automated_work_gate


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
def llm_client(app):
    """LLM gate open only (enough for index / presence / approve / decline)."""
    with TestClient(app) as c:
        r = c.post(
            "/api/setup/llm",
            json={"provider": "ollama", "base_url": "http://localhost:11434/v1", "model": "llama3.1"},
        )
        assert r.status_code == 204
        yield c


@pytest.fixture
def work_client(app):
    """Full automated-work gate open (needed for build/deliver/email)."""
    with TestClient(app) as c:
        open_automated_work_gate(c)
        yield c


def test_index(llm_client):
    res = llm_client.get("/api/digest")
    assert res.status_code == 200
    assert res.json() == {"surface": "digest", "phase": 1, "status": "live"}


def test_get_digest_empty_day(work_client):
    # No postings discovered -> the empty-day digest with a "what I searched" note.
    res = work_client.get("/api/digest/camp-dig-1")
    assert res.status_code == 200
    body = res.json()
    assert body["campaign_id"] == "camp-dig-1"
    assert body["empty"] is True
    assert body["rows"] == []
    assert body["note"]  # FR-DIG-6 empty-day note present.


def test_deliver_empty_digest(work_client):
    res = work_client.post("/api/digest/camp-dig-2/deliver")
    assert res.status_code == 200
    body = res.json()
    assert body["campaign_id"] == "camp-dig-2"
    assert body["row_count"] == 0
    assert body["empty"] is True
    # An empty digest still produces an email subject + notify handle.
    assert body["email_subject"]
    assert "delivered_channels" in body


def test_get_email_empty_day(work_client):
    res = work_client.get("/api/digest/camp-dig-3/email")
    assert res.status_code == 200
    body = res.json()
    assert body["campaign_id"] == "camp-dig-3"
    assert body["row_count"] == 0
    assert body["subject"]
    assert "Your daily digest</h1>" in body["html"]  # branded heading (P1-4 polish)


def test_get_digest_blocked_before_automated_work_gate(llm_client):
    # /api/digest/{id} carries require_automated_work; LLM-only is not enough.
    assert llm_client.get("/api/digest/camp-x").status_code == 409
    assert llm_client.post("/api/digest/camp-x/deliver").status_code == 409
    assert llm_client.get("/api/digest/camp-x/email").status_code == 409


def test_set_presence_signal(llm_client):
    # The presence pre-empt signal is accepted (204) and routed to the notifier.
    res = llm_client.post("/api/digest/presence", json={"present": True})
    assert res.status_code == 204
    # Default body is present=True; explicit False is also accepted.
    assert llm_client.post("/api/digest/presence", json={"present": False}).status_code == 204
    assert llm_client.post("/api/digest/presence", json={}).status_code == 204


def _seed_digest_app(client, aid):
    """Seed a real application row so approve/decline have a valid FK target (the
    digest acts on real postings/applications; a Decision needs an applications row)."""
    from applicant.core.entities.application import Application
    from applicant.core.ids import ApplicationId, CampaignId, JobPostingId

    storage = client.app.state.container.storage
    storage.applications.add(
        Application(id=ApplicationId(aid), campaign_id=CampaignId("camp-dig-1"), posting_id=JobPostingId(""))
    )
    storage.commit()


def test_approve_records_decision(llm_client):
    _seed_digest_app(llm_client, "app-dig-1")
    res = llm_client.post("/api/digest/applications/app-dig-1/approve")
    assert res.status_code == 201
    body = res.json()
    assert body["type"] == "approve"
    assert body["decision_id"]


def test_decline_with_feedback_records_delta(llm_client):
    _seed_digest_app(llm_client, "app-dig-2")
    res = llm_client.post(
        "/api/digest/applications/app-dig-2/decline",
        json={"feedback_text": "Too senior for me right now.", "criteria_delta": {"seniority": "mid"}},
    )
    assert res.status_code == 201
    body = res.json()
    assert body["type"] == "decline"
    assert body["feedback_text"] == "Too senior for me right now."
    assert body["criteria_delta"] == {"seniority": "mid"}


def test_decline_blank_feedback_is_422(llm_client):
    # FR-FB-1: mandatory decline feedback; blank/whitespace -> 422.
    res = llm_client.post(
        "/api/digest/applications/app-dig-3/decline",
        json={"feedback_text": "   "},
    )
    assert res.status_code == 422
    assert "feedback" in res.json()["detail"].lower()


def test_decline_missing_feedback_defaults_to_blank_422(llm_client):
    # Omitting feedback_text entirely defaults to "" -> still the mandatory-feedback 422.
    res = llm_client.post("/api/digest/applications/app-dig-4/decline", json={})
    assert res.status_code == 422


def test_router_blocked_before_llm_gate(app):
    with TestClient(app) as c:
        assert c.get("/api/digest").status_code == 409
        assert c.post("/api/digest/applications/x/approve").status_code == 409
