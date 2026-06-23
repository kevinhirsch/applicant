"""Coverage: the consolidated agent-status router (FR-AGENT-7 / FR-OBS-2 / FR-UI).

``GET /api/agent/status/{campaign_id}`` assembles a plain-language ``now`` / ``next``
/ ``recent`` snapshot FRESH from the live read-only sources (scheduler heartbeat,
the per-campaign run status + FR-AGENT-7 intent, pending actions, and recent
application history). These tests prove:

* the real-state summary is assembled from those sources (first-person voice, the
  intent surfaced under ``next``, today's count under ``now``); and
* an erroring source contributes NOTHING rather than fabricating activity
  (FR-AGENT-5) — the endpoint still returns a well-formed body.

Hermetic: in-memory storage, real container services, gate opened via the shared
``open_automated_work_gate`` helper.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from applicant.app.main import create_app
from tests.conftest import open_automated_work_gate


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        open_automated_work_gate(c)
        yield c


def _campaign(client) -> str:
    return client.post("/api/campaigns", json={"name": "Backend"}).json()["id"]


def test_gated_until_llm_configured():
    # Without the gates open, the surface 409s like its sibling agent routers.
    with TestClient(create_app()) as c:
        assert c.get("/api/agent/status/anything").status_code == 409


def test_snapshot_assembles_now_next_recent(client):
    cid = _campaign(client)
    # Record a run so the FR-AGENT-7 intent + today's count have real state.
    container = client.app.state.container
    container.agent_run_service.start_run(
        cid, "Deliver a digest of 12 viable roles for your review"
    )

    body = client.get(f"/api/agent/status/{cid}").json()
    assert body["campaign_id"] == cid
    # now: first-person voice, today's applied count vs the daily budget.
    assert body["now"]["sentence"].lower().startswith("right now i")
    assert "daily_budget" in body["now"]
    assert body["now"]["applied_today"] == 0
    # next: the intent sentence is surfaced verbatim and woven into first person.
    assert body["next"]["intent"] == "Deliver a digest of 12 viable roles for your review"
    assert body["next"]["sentence"].startswith("Next I'll deliver a digest")
    # next: pending-actions count is reported (zero here, but present + honest).
    assert body["next"]["pending_actions"] == 0
    # recent: a well-formed list (empty until applications exist).
    assert body["recent"] == []


def test_snapshot_reflects_pending_actions(client):
    cid = _campaign(client)
    container = client.app.state.container
    container.pending_actions_service.materialize(cid, "digest_approval", "Review 5 roles")
    body = client.get(f"/api/agent/status/{cid}").json()
    assert body["next"]["pending_actions"] == 1


def test_snapshot_degrades_when_a_source_errors(client, monkeypatch):
    """An erroring source omits its contribution; no fabrication, no 500."""
    cid = _campaign(client)
    container = client.app.state.container

    # Make the recent-history source raise — the endpoint must still answer.
    def _boom(*a, **k):
        raise RuntimeError("history backend down")

    monkeypatch.setattr(
        container.admin_query_service, "application_history", _boom
    )
    # And make the run-status source raise too (the 'now'/'next' source).
    monkeypatch.setattr(container.agent_run_service, "status", _boom)

    r = client.get(f"/api/agent/status/{cid}")
    assert r.status_code == 200
    body = r.json()
    # recent omitted -> empty list, not invented rows.
    assert body["recent"] == []
    # now/next still render a sensible default sentence without the failed source's
    # numbers (no applied_today / daily_budget fabricated).
    assert "applied_today" not in body["now"]
    assert "daily_budget" not in body["now"]
    assert body["now"]["sentence"].lower().startswith("right now i")
    assert body["next"]["sentence"].startswith("Next I'll")
