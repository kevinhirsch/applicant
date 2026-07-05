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


# --- (d) dark-engine audit item 11: free-text rejection reason ------------------


def test_manual_rejected_outcome_with_reason_persists_rejection_signal(client):
    """The optional ``reason`` on a manual "rejected" outcome is layered onto the
    RejectionSignal audit trail (``process_rejection_signal``) WITHOUT touching
    the single clean state transition/OutcomeEvent ``record_manual_outcome``
    already performs."""
    container = client.app.state.container
    _seed(container, "c-6", "a-6", status=ApplicationState.AWAITING_RESPONSE)

    r = client.post(
        "/api/post-submission/applications/a-6/outcome",
        json={"outcome_type": "rejected", "reason": "Role was put on hold."},
    )
    assert r.status_code == 201

    board = client.get("/api/post-submission/c-6").json()
    assert board["applications"][0]["status"] == "REJECTED"

    # Exactly one "rejected" OutcomeEvent -- the reason must not double-record.
    outcomes = container.storage.outcomes.list_for_application(ApplicationId("a-6"))
    rejected_events = [o for o in outcomes if o.type == "rejected"]
    assert len(rejected_events) == 1

    signals = container.storage.rejection_signals.list_for_application(ApplicationId("a-6"))
    assert len(signals) == 1
    assert signals[0].signal_text == "Role was put on hold."
    assert signals[0].source.value == "manual"


def test_manual_rejected_outcome_without_reason_records_no_signal(client):
    container = client.app.state.container
    _seed(container, "c-7", "a-7", status=ApplicationState.AWAITING_RESPONSE)

    r = client.post(
        "/api/post-submission/applications/a-7/outcome",
        json={"outcome_type": "rejected"},
    )
    assert r.status_code == 201
    signals = container.storage.rejection_signals.list_for_application(ApplicationId("a-7"))
    assert signals == []


def test_reason_on_a_non_rejected_outcome_is_ignored(client):
    container = client.app.state.container
    _seed(container, "c-8", "a-8", status=ApplicationState.AWAITING_RESPONSE)

    r = client.post(
        "/api/post-submission/applications/a-8/outcome",
        json={"outcome_type": "offer", "reason": "irrelevant text"},
    )
    assert r.status_code == 201
    signals = container.storage.rejection_signals.list_for_application(ApplicationId("a-8"))
    assert signals == []


# --- (e) dark-engine audit item 13: archive -------------------------------------


def test_archive_closes_out_an_archivable_application(client):
    container = client.app.state.container
    _seed(container, "c-9", "a-9", status=ApplicationState.AWAITING_RESPONSE)

    r = client.post("/api/post-submission/applications/a-9/archive")
    assert r.status_code == 200
    body = r.json()
    assert body["application_id"] == "a-9"
    assert body["status"] == "ARCHIVED"

    board = client.get("/api/post-submission/c-9").json()
    assert board["applications"][0]["status"] == "ARCHIVED"


def test_archive_rejects_a_not_yet_archivable_application_with_409(client):
    container = client.app.state.container
    # SUBMITTED_BY_USER ("Applied" bucket) can't jump straight to ARCHIVED.
    _seed(container, "c-10", "a-10", status=ApplicationState.SUBMITTED_BY_USER)

    r = client.post("/api/post-submission/applications/a-10/archive")
    assert r.status_code == 409

    board = client.get("/api/post-submission/c-10").json()
    assert board["applications"][0]["status"] == "SUBMITTED_BY_USER"


def test_archive_unknown_application_is_404(client):
    r = client.post("/api/post-submission/applications/does-not-exist/archive")
    assert r.status_code == 404


# --- (f) dark-engine audit B2 items 8/9/60: the ghosting/follow-up "attention" read --


def test_attention_endpoint_is_registered_and_well_formed_when_empty(client):
    paths = _registered_paths(client.app)
    assert "/api/post-submission/{campaign_id}/attention" in paths

    r = client.get("/api/post-submission/c-empty/attention")
    assert r.status_code == 200
    assert r.json() == {"campaign_id": "c-empty", "ghosted": [], "followups_due": []}


def test_attention_endpoint_reads_back_ghosting_and_followup_pending_actions(client):
    container = client.app.state.container
    _seed(container, "c-attn", "a-attn-1", status=ApplicationState.AWAITING_RESPONSE)
    _seed(container, "c-attn", "a-attn-2", status=ApplicationState.AWAITING_RESPONSE)

    pending = container.pending_actions_service
    pending.materialize(
        CampaignId("c-attn"),
        "ghosting_flag",
        "Likely gone silent: Acme",
        application_id=ApplicationId("a-attn-1"),
        payload={"sla_days": 21, "submission_age_days": 30},
        dedup_key="ghosting_flag:a-attn-1",
    )
    pending.materialize(
        CampaignId("c-attn"),
        "followup_draft",
        "Follow-up ready to review: Acme",
        application_id=ApplicationId("a-attn-2"),
        payload={"subject": "Checking in", "body": "Hi, ..."},
        dedup_key="followup_draft:a-attn-2",
    )
    # An unrelated pending-action kind must not leak into either bucket.
    pending.materialize(CampaignId("c-attn"), "agent_question", "Unrelated question?")

    r = client.get("/api/post-submission/c-attn/attention")
    assert r.status_code == 200
    body = r.json()
    assert body["campaign_id"] == "c-attn"
    assert len(body["ghosted"]) == 1
    assert body["ghosted"][0]["application_id"] == "a-attn-1"
    assert body["ghosted"][0]["payload"]["sla_days"] == 21
    assert len(body["followups_due"]) == 1
    assert body["followups_due"][0]["application_id"] == "a-attn-2"
    assert body["followups_due"][0]["payload"]["body"] == "Hi, ..."


def test_attention_endpoint_llm_gate_blocks_when_not_configured():
    with TestClient(create_app()) as c:
        r = c.get("/api/post-submission/c-1/attention")
        assert r.status_code == 409


# --- (g) dark-engine audit B2 item 7: approve + schedule a drafted follow-up --


def _seed_follow_up_draft(container, cid, aid, *, subject="Checking in", body="Hi, ..."):
    pending = container.pending_actions_service
    pending.materialize(
        CampaignId(cid),
        "followup_draft",
        f"Follow-up ready to review: {aid}",
        application_id=ApplicationId(aid),
        payload={"subject": subject, "body": body},
        dedup_key=f"followup_draft:{aid}",
    )


def test_approve_follow_up_route_is_registered(client):
    paths = _registered_paths(client.app)
    assert "/api/post-submission/applications/{application_id}/follow-up/approve" in paths


def test_approve_follow_up_schedules_it_and_clears_the_draft(client):
    container = client.app.state.container
    _seed(container, "c-fu1", "a-fu1", status=ApplicationState.AWAITING_RESPONSE)
    _seed_follow_up_draft(container, "c-fu1", "a-fu1", subject="Checking in", body="Hi there.")

    r = client.post("/api/post-submission/applications/a-fu1/follow-up/approve")
    assert r.status_code == 201
    body = r.json()
    assert body["application_id"] == "a-fu1"
    assert body["status"] == "SCHEDULED"
    assert body["subject"] == "Checking in"
    assert body["body"] == "Hi there."
    assert body["scheduled_at"]
    assert body["follow_up_id"]

    # The draft is resolved -- it no longer appears on the attention feed.
    attention = client.get("/api/post-submission/c-fu1/attention").json()
    assert attention["followups_due"] == []


def test_approve_follow_up_lets_the_owner_edit_subject_and_body(client):
    container = client.app.state.container
    _seed(container, "c-fu2", "a-fu2", status=ApplicationState.AWAITING_RESPONSE)
    _seed_follow_up_draft(container, "c-fu2", "a-fu2", subject="Original", body="Original body")

    r = client.post(
        "/api/post-submission/applications/a-fu2/follow-up/approve",
        json={"subject": "Edited subject", "body": "Edited body"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["subject"] == "Edited subject"
    assert body["body"] == "Edited body"


def test_approve_follow_up_without_a_draft_is_404(client):
    container = client.app.state.container
    _seed(container, "c-fu3", "a-fu3", status=ApplicationState.AWAITING_RESPONSE)

    r = client.post("/api/post-submission/applications/a-fu3/follow-up/approve")
    assert r.status_code == 404


def test_approve_follow_up_unknown_application_is_404():
    with TestClient(create_app()) as c:
        r = c.post(
            "/api/setup/llm",
            json={"provider": "ollama", "base_url": "http://localhost:11434/v1", "model": "llama3.1"},
        )
        assert r.status_code == 204
        r = c.post("/api/post-submission/applications/does-not-exist/follow-up/approve")
        assert r.status_code == 404


def test_approve_follow_up_twice_only_schedules_once(client):
    container = client.app.state.container
    _seed(container, "c-fu4", "a-fu4", status=ApplicationState.AWAITING_RESPONSE)
    _seed_follow_up_draft(container, "c-fu4", "a-fu4")

    first = client.post("/api/post-submission/applications/a-fu4/follow-up/approve")
    second = client.post("/api/post-submission/applications/a-fu4/follow-up/approve")

    assert first.status_code == 201
    assert second.status_code == 404


def test_approve_follow_up_llm_gate_blocks_when_not_configured():
    with TestClient(create_app()) as c:
        r = c.post("/api/post-submission/applications/a-1/follow-up/approve")
        assert r.status_code == 409
