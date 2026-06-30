"""Feedback endpoints + attribute binding/dynamic-add round-trips (FR-FB-2/3, FR-ATTR-2/4/5)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from applicant.app.main import create_app
from applicant.core.ids import new_id


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


def _open_gate(client):
    assert (
        client.post(
            "/api/setup/llm",
            json={"provider": "ollama", "base_url": "http://x/v1", "model": "llama3.1"},
        ).status_code
        == 204
    )


@pytest.mark.integration
def test_freetext_feedback_folds_into_learning(client):
    _open_gate(client)
    cid = client.post("/api/campaigns", json={"name": "C"}).json()["id"]
    r = client.post(
        "/api/feedback/freetext",
        json={"campaign_id": cid, "text": "prefer remote backend roles", "criteria_delta": {}},
    )
    assert r.status_code == 201
    assert r.json()["folded"] is True


@pytest.mark.integration
def test_survey_cross_references_attribute_cloud(client):
    _open_gate(client)
    cid = client.post("/api/campaigns", json={"name": "C"}).json()["id"]
    r = client.post(
        "/api/feedback/survey",
        json={"campaign_id": cid, "answers": {"Preferred location": "Remote"}},
    )
    assert r.status_code == 201
    body = r.json()
    # Non-integral parsed input auto-applies to the attribute cloud (FR-LEARN-4).
    assert "Preferred location" in body["applied"]


@pytest.mark.integration
def test_dynamic_ai_add_attribute(client, seeded_campaign):
    _open_gate(client)
    cid = seeded_campaign()  # attributes.campaign_id is a real FK — seed the parent
    r = client.post(
        "/api/attributes/ai-add",
        json={"campaign_id": cid, "name": "Portfolio URL", "value": "https://me.dev"},
    )
    assert r.status_code == 201
    listing = client.get(f"/api/attributes/{cid}").json()
    assert any(a["name"] == "Portfolio URL" for a in listing["items"])


@pytest.mark.integration
def test_ai_add_sensitive_rejected(client):
    _open_gate(client)
    cid = new_id()
    r = client.post(
        "/api/attributes/ai-add",
        json={"campaign_id": cid, "name": "Gender", "value": "anything"},
    )
    assert r.status_code == 409


@pytest.mark.integration
def test_field_binding_persists(client, seeded_campaign):
    _open_gate(client)
    cid = seeded_campaign()  # attributes.campaign_id is a real FK — seed the parent
    attr = client.post(
        "/api/attributes",
        json={"campaign_id": cid, "name": "Email", "value": "me@x.dev"},
    ).json()
    r = client.post(
        "/api/attributes/bindings",
        json={
            "site_key": "workday",
            "field_selector": "emailAddress",
            "attribute_id": attr["id"],
            "shared": True,
        },
    )
    assert r.status_code == 201
    assert r.json()["is_shared"] is True
