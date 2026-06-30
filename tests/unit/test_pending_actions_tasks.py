"""Pending-actions-as-tasks: snooze, bulk resolve, and task metadata (#295).

Exercises the extended :class:`PendingActionsService` + its router end-to-end on
the in-memory storage with real container services. Reuses the existing service —
no parallel TasksService.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from applicant.app.main import create_app
from applicant.core.ids import CampaignId, new_id


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        r = c.post(
            "/api/setup/llm",
            json={"provider": "ollama", "base_url": "http://localhost:11434/v1", "model": "llama3.1"},
        )
        assert r.status_code == 204
        yield c


def _svc(client):
    return client.app.state.container.pending_actions_service


# --- list metadata ----------------------------------------------------------


def test_list_returns_task_metadata_sorted_by_priority(client):
    svc = _svc(client)
    cid = CampaignId(new_id())
    svc.materialize(cid, "agent_question", "Which city?")
    svc.materialize(cid, "emergency_handoff", "Take over now")

    r = client.get(f"/api/pending-actions/{cid}")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 2
    # Every item carries the derived task fields.
    for it in items:
        assert "age_label" in it and "urgency" in it and "priority" in it
        assert "campaign_id" in it
    # Highest-priority (emergency hand-off) floats to the top.
    assert items[0]["title"] == "Take over now"
    assert items[0]["priority"] >= items[1]["priority"]


# --- snooze -----------------------------------------------------------------


def test_snooze_hides_item_until_due(client):
    svc = _svc(client)
    cid = CampaignId(new_id())
    action = svc.materialize(cid, "agent_question", "Which city?")

    r = client.post(f"/api/pending-actions/{action.id}/snooze")
    assert r.status_code == 200
    assert r.json()["snoozed_until"]

    # Snoozed → gone from the default home base...
    assert client.get(f"/api/pending-actions/{cid}").json()["count"] == 0
    # ...but still there for an include_snoozed view.
    everything = client.get(f"/api/pending-actions/{cid}?include_snoozed=true").json()
    assert everything["count"] == 1
    assert everything["items"][0]["snoozed"] is True


def test_snooze_until_explicit_timestamp(client):
    svc = _svc(client)
    cid = CampaignId(new_id())
    action = svc.materialize(cid, "agent_question", "Which city?")
    until = (datetime.now(UTC) + timedelta(hours=3)).isoformat()
    r = client.post(f"/api/pending-actions/{action.id}/snooze", json={"until": until})
    assert r.status_code == 200
    assert r.json()["snoozed_until"].startswith(until[:16])


def test_snooze_past_time_keeps_item_visible(client):
    svc = _svc(client)
    cid = CampaignId(new_id())
    action = svc.materialize(cid, "agent_question", "Which city?")
    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    client.post(f"/api/pending-actions/{action.id}/snooze", json={"until": past})
    # A past wake time is already due → still visible.
    assert client.get(f"/api/pending-actions/{cid}").json()["count"] == 1


def test_snooze_unknown_action_is_404(client):
    r = client.post(f"/api/pending-actions/{new_id()}/snooze")
    assert r.status_code == 404


def test_snooze_invalid_until_is_422(client):
    svc = _svc(client)
    cid = CampaignId(new_id())
    action = svc.materialize(cid, "agent_question", "Q")
    r = client.post(f"/api/pending-actions/{action.id}/snooze", json={"until": "not-a-date"})
    assert r.status_code == 422


# --- bulk resolve -----------------------------------------------------------


def test_bulk_resolve_clears_listed_items(client):
    svc = _svc(client)
    cid = CampaignId(new_id())
    a1 = svc.digest_approval(cid, posting_id="p1", title="Role 1")
    a2 = svc.digest_approval(cid, posting_id="p2", title="Role 2")
    a3 = svc.materialize(cid, "agent_question", "keep me")

    r = client.post(
        f"/api/pending-actions/{cid}/resolve-bulk",
        json={"action_ids": [a1.id, a2.id]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["resolved_count"] == 2
    assert set(body["resolved"]) == {str(a1.id), str(a2.id)}

    remaining = client.get(f"/api/pending-actions/{cid}").json()
    assert remaining["count"] == 1
    assert remaining["items"][0]["id"] == a3.id


def test_bulk_resolve_skips_other_campaigns_ids(client):
    svc = _svc(client)
    cid = CampaignId(new_id())
    other = CampaignId(new_id())
    mine = svc.materialize(cid, "agent_question", "mine")
    theirs = svc.materialize(other, "agent_question", "theirs")

    r = client.post(
        f"/api/pending-actions/{cid}/resolve-bulk",
        json={"action_ids": [mine.id, theirs.id]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["resolved"] == [str(mine.id)]
    assert str(theirs.id) in body["skipped"]
    # The other campaign's item is untouched.
    assert client.get(f"/api/pending-actions/{other}").json()["count"] == 1
