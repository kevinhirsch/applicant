"""Documents router integration: the interactive review loop over HTTP.

Exercises the Phase 3 review surface endpoints end-to-end against the in-process
app (hermetic: no TeX/LLM): generate cover letter on demand + screening answer
(FR-RESUME-10, FR-ANSWER-1), open the review, run add/subtract/free-text turns
(FR-RESUME-8), enforce the review gate (409 until approved, FR-RESUME-1/8), and the
grayed aggressiveness setting (FR-RESUME-9).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from applicant.app.main import create_app


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as c:
        # Open the LLM gate (FR-UI-5) so the documents router is reachable.
        c.post(
            "/api/setup/llm",
            json={"provider": "ollama", "base_url": "http://localhost:11434/v1", "model": "llama3.1"},
        )
        yield c


@pytest.mark.integration
def test_cover_letter_on_demand_and_review_gate(client):
    cid, aid = "camp-doc-1", "app-doc-1"
    # A role with no override + default off -> no cover letter (FR-RESUME-10).
    none = client.post(
        "/api/documents/cover-letter",
        json={"campaign_id": cid, "application_id": aid, "true_source": "Built pipelines.", "campaign_default": False},
    )
    assert none.status_code == 201
    assert none.json()["generated"] is False

    # A role that requires one -> generated, stored unapproved.
    made = client.post(
        "/api/documents/cover-letter",
        json={
            "campaign_id": cid,
            "application_id": aid,
            "true_source": "Built Python pipelines.",
            "jd_terms": ["Python"],
            "role_requires": True,
        },
    )
    assert made.status_code == 201
    body = made.json()
    assert body["generated"] is True and body["approved"] is False
    doc_id = body["id"]

    # Review gate blocks submission while unapproved (FR-RESUME-1/8).
    blocked = client.post(f"/api/documents/applications/{aid}/ensure-submittable")
    assert blocked.status_code == 409

    # Open the review + run add / subtract / free-text turns (FR-RESUME-8).
    assert client.post(f"/api/documents/{doc_id}/review").status_code == 201
    for kind in ("free_text", "add", "subtract"):
        turn = client.post(
            f"/api/documents/{doc_id}/turn",
            json={"kind": kind, "instruction": "make it more concise"},
        )
        assert turn.status_code == 201
        # The em-dash filter re-runs on every turn (FR-RESUME-5): content stays clean.
        content = turn.json()["redline_state"].get("content", "")
        assert "—" not in content

    # Approve -> gate opens (FR-RESUME-8).
    assert client.post(f"/api/documents/{doc_id}/approve").status_code == 201
    # #284: assert the BODY confirms the verdict, not merely a 200 status.
    open_r = client.post(f"/api/documents/applications/{aid}/ensure-submittable")
    assert open_r.status_code == 200
    body = open_r.json()
    assert body["submittable"] is True
    assert body["application_id"] == aid


@pytest.mark.integration
def test_screening_answer_classified_and_reviewed(client):
    cid, aid = "camp-doc-2", "app-doc-2"
    res = client.post(
        "/api/documents/screening-answer",
        json={
            "campaign_id": cid,
            "application_id": aid,
            "question": "Why do you want to work here?",
            "true_source": "I enjoy building data platforms.",
        },
    )
    assert res.status_code == 201
    assert res.json()["type"] == "screening_answer"
    assert res.json()["approved"] is False


@pytest.mark.integration
def test_aggressiveness_setting_is_live_after_187(client):
    res = client.post("/api/documents/aggressiveness", json={"aggressiveness": 500})
    assert res.status_code == 200
    body = res.json()
    assert body["aggressiveness"] == 100  # clamped (FR-RESUME-9)
    assert body["dormant_ui"] is False  # UI control is live after #187


# CRIT-profile: banned-phrase ("no-AI-look") list editor (FR-RESUME-5).
@pytest.mark.integration
def test_banned_phrases_get_returns_seed_and_empty_custom(client):
    res = client.get("/api/documents/banned-phrases")
    assert res.status_code == 200
    body = res.json()
    # The curated baseline is always present, read-only.
    assert "delve into" in body["seed_phrases"]
    # No custom additions until the owner adds some.
    assert body["phrases"] == []


@pytest.mark.integration
def test_banned_phrases_set_persists_and_round_trips(client):
    saved = client.post(
        "/api/documents/banned-phrases",
        json={"phrases": ["circle back", "  ", "synergize"]},
    )
    assert saved.status_code == 200
    # Blank entries are dropped by the engine; real ones are kept.
    assert saved.json()["phrases"] == ["circle back", "synergize"]
    # Persists across requests (held on the container-singleton material service).
    again = client.get("/api/documents/banned-phrases")
    assert again.json()["phrases"] == ["circle back", "synergize"]
    assert "delve into" in again.json()["seed_phrases"]
