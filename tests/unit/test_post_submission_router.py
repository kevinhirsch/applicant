"""Reachability + real fields for the Post-Submission tracker router (#4 of the
design-audit Top-25: "wire the post-submission tracker to the front-door").

``PostSubmissionService`` already ran the full post-submission state machine
with zero router/front-door callers. This proves the wired endpoints — not
just the service methods in isolation:

  (a) ``/api/post-submission/{campaign_id}`` and
      ``/api/post-submission/applications/{application_id}/outcome`` are
      REGISTERED routes on the booted app and return non-404 via ``TestClient``;
  (b) a seeded campaign returns REAL tracker rows (status / role / signals);
  (c) the manual-outcome write transitions status where §7 defines one, records
      a MANUAL outcome event, and 422s on an unrecognized outcome type.

Hermetic: in-memory storage, real container services, LLM gate opened like the
peer router tests (test_gallery_router.py).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from applicant.app.main import create_app
from applicant.core.entities.application import Application
from applicant.core.entities.campaign import Campaign
from applicant.core.entities.outcome_event import OutcomeEvent
from applicant.core.entities.submission_snapshot import SubmissionSnapshot
from applicant.core.ids import (
    ApplicationId,
    CampaignId,
    JobPostingId,
    OutcomeEventId,
    SubmissionSnapshotId,
)
from applicant.core.state_machine import ApplicationState


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        # Open the LLM gate (the router carries require_llm_configured).
        r = c.post(
            "/api/setup/llm",
            json={"provider": "ollama", "base_url": "http://localhost:11434/v1", "model": "llama3.1"},
        )
        assert r.status_code == 204
        yield c


def _registered_paths(app) -> set[str]:
    """All endpoint paths registered on the app (flattening the mount wrapper)."""
    paths: set[str] = set()
    for r in app.routes:
        p = getattr(r, "path", None)
        if p:
            paths.add(p)
        orig = getattr(r, "original_router", None)
        if orig is not None:
            for sub in getattr(orig, "routes", []):
                sp = getattr(sub, "path", None)
                if sp:
                    paths.add(sp)
    return paths


def _seed(container, cid, aid, *, status=ApplicationState.AWAITING_RESPONSE, role="Engineer"):
    container.storage.campaigns.add(Campaign(id=CampaignId(cid), name="Tracker"))
    app = Application(
        id=ApplicationId(aid),
        campaign_id=CampaignId(cid),
        posting_id=JobPostingId(f"posting-{aid}"),
        status=status,
        role_name=role,
    )
    container.storage.applications.add(app)
    container.storage.outcomes.add(
        OutcomeEvent(id=OutcomeEventId(f"oe-{aid}"), application_id=app.id, type="submitted")
    )
    container.storage.submission_snapshots.add(
        SubmissionSnapshot(id=SubmissionSnapshotId(f"snap-{aid}"), application_id=app.id)
    )
    container.storage.commit()
    return app


# --- (a) reachability: the routes are registered and non-404 -------------------


def test_tracker_routes_are_registered(client):
    paths = _registered_paths(client.app)
    assert "/api/post-submission/{campaign_id}" in paths
    assert "/api/post-submission/applications/{application_id}/outcome" in paths


def test_tracker_board_is_reachable_not_404(client):
    r = client.get("/api/post-submission/c-empty")
    assert r.status_code != 404
    assert r.status_code == 200


# --- (b) seeded campaign returns REAL tracker rows ------------------------------


def test_tracker_board_returns_real_application_rows(client):
    container = client.app.state.container
    _seed(container, "c-1", "a-1", status=ApplicationState.AWAITING_RESPONSE)

    r = client.get("/api/post-submission/c-1")
    assert r.status_code == 200
    body = r.json()
    assert body["campaign_id"] == "c-1"
    rows = body["applications"]
    assert len(rows) == 1
    row = rows[0]
    assert row["application_id"] == "a-1"
    assert row["status"] == "AWAITING_RESPONSE"
    assert row["role_name"] == "Engineer"
    assert row["signals"] == []


def test_tracker_board_excludes_pre_submission_applications(client):
    container = client.app.state.container
    _seed(container, "c-2", "a-early", status=ApplicationState.PREFILLING)

    r = client.get("/api/post-submission/c-2")
    assert r.status_code == 200
    assert r.json()["applications"] == []


def test_tracker_board_empty_campaign_is_well_formed(client):
    r = client.get("/api/post-submission/c-none")
    assert r.status_code == 200
    assert r.json() == {"campaign_id": "c-none", "applications": []}


# --- (c) manual outcome write ---------------------------------------------------


def test_manual_rejected_outcome_transitions_status(client):
    container = client.app.state.container
    _seed(container, "c-3", "a-3", status=ApplicationState.AWAITING_RESPONSE)

    r = client.post(
        "/api/post-submission/applications/a-3/outcome",
        json={"outcome_type": "rejected"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["application_id"] == "a-3"
    assert body["type"] == "rejected"
    assert body["source"] == "manual"

    board = client.get("/api/post-submission/c-3").json()
    assert board["applications"][0]["status"] == "REJECTED"


def test_manual_interview_signal_layers_onto_row_without_changing_status(client):
    container = client.app.state.container
    _seed(container, "c-4", "a-4", status=ApplicationState.AWAITING_RESPONSE)

    r = client.post(
        "/api/post-submission/applications/a-4/outcome",
        json={"outcome_type": "interview_invited"},
    )
    assert r.status_code == 201

    board = client.get("/api/post-submission/c-4").json()
    row = board["applications"][0]
    assert row["status"] == "AWAITING_RESPONSE"
    assert row["signals"] == ["interview_invited"]


def test_manual_outcome_unrecognized_type_is_422(client):
    container = client.app.state.container
    _seed(container, "c-5", "a-5")

    r = client.post(
        "/api/post-submission/applications/a-5/outcome",
        json={"outcome_type": "not-a-real-outcome"},
    )
    assert r.status_code == 422


def test_manual_outcome_unknown_application_is_404(client):
    r = client.post(
        "/api/post-submission/applications/does-not-exist/outcome",
        json={"outcome_type": "rejected"},
    )
    assert r.status_code == 404


def test_llm_gate_blocks_tracker_when_not_configured():
    with TestClient(create_app()) as c:
        r = c.get("/api/post-submission/c-1")
        assert r.status_code == 409
