"""Coverage: the ACE playbook delta-application surface (dark-engine audit item 46).

``PlaybookService.apply_deltas``/``empty`` (structured add/revise/retire updates to
a curated per-ATS playbook) had zero real callers — everything reachable in the
front door went through the unrelated free-text ``save_playbook``/``update_playbook``
chat tools instead. This exercises the new
``GET/POST /api/agent-memory/playbooks/{ats}`` surface: applying deltas actually
persists on the campaign's ``learning_state`` (namespaced ``ace_playbooks``) via the
real ``PlaybookService``, is readable back, and builds an auditable trail.

Hermetic: in-memory storage, real container services (mirrors
``test_cov_agent_memory_router.py``'s fixture).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from applicant.app.main import create_app
from applicant.core.entities.campaign import Campaign
from applicant.core.ids import CampaignId


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        r = c.post(
            "/api/setup/llm",
            json={"provider": "ollama", "base_url": "http://localhost:11434/v1", "model": "llama3.1"},
        )
        assert r.status_code == 204
        yield c


def _make_campaign(client, campaign_id: str = "camp-1") -> str:
    storage = client.app.state.container.storage
    storage.campaigns.add(Campaign(id=CampaignId(campaign_id), name="Test Campaign"))
    storage.commit()
    return campaign_id


def test_gated_until_llm_configured():
    with TestClient(create_app()) as c:
        r = c.get("/api/agent-memory/playbooks/workday", params={"campaign_id": "camp-1"})
        assert r.status_code == 409


def test_empty_playbook_for_unknown_campaign_is_404(client):
    r = client.get("/api/agent-memory/playbooks/workday", params={"campaign_id": "nope"})
    assert r.status_code == 404


def test_empty_playbook_has_no_entries_yet(client):
    cid = _make_campaign(client)
    r = client.get("/api/agent-memory/playbooks/workday", params={"campaign_id": cid})
    assert r.status_code == 200
    body = r.json()
    assert body["ats"] == "workday"
    assert body["entries"] == []
    assert body["audit"] == []


def test_apply_deltas_requires_at_least_one_delta(client):
    cid = _make_campaign(client)
    r = client.post(
        "/api/agent-memory/playbooks/workday/apply-deltas",
        json={"campaign_id": cid, "deltas": []},
    )
    assert r.status_code == 400


def test_apply_deltas_unknown_campaign_is_404(client):
    r = client.post(
        "/api/agent-memory/playbooks/workday/apply-deltas",
        json={"campaign_id": "nope", "deltas": [{"op": "add", "key": "k", "text": "t"}]},
    )
    assert r.status_code == 404


def test_add_delta_creates_entry_and_is_readable_back(client):
    cid = _make_campaign(client)
    r = client.post(
        "/api/agent-memory/playbooks/workday/apply-deltas",
        json={
            "campaign_id": cid,
            "deltas": [
                {"op": "add", "key": "wait-for-spinner", "text": "Wait for the loading spinner to clear."}
            ],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert len(body["applied"]) == 1
    assert body["applied"][0]["op"] == "add"
    assert [e["key"] for e in body["entries"]] == ["wait-for-spinner"]
    assert len(body["audit"]) == 1
    assert body["audit"][0]["op"] == "add"
    assert "applied_at" in body["audit"][0]

    # Real persistence: a fresh GET reflects the same state, and it survives on
    # the campaign's learning_state (not just the response of the POST).
    read = client.get("/api/agent-memory/playbooks/workday", params={"campaign_id": cid}).json()
    assert [e["key"] for e in read["entries"]] == ["wait-for-spinner"]
    assert len(read["audit"]) == 1

    storage = client.app.state.container.storage
    campaign = storage.campaigns.get(CampaignId(cid))
    assert "ace_playbooks" in campaign.learning_state
    assert campaign.learning_state["ace_playbooks"]["workday"]["entries"][0]["key"] == "wait-for-spinner"


def test_revise_bumps_revision_and_retire_removes_entry(client):
    cid = _make_campaign(client)
    client.post(
        "/api/agent-memory/playbooks/workday/apply-deltas",
        json={"campaign_id": cid, "deltas": [{"op": "add", "key": "k1", "text": "v1"}]},
    )
    r = client.post(
        "/api/agent-memory/playbooks/workday/apply-deltas",
        json={"campaign_id": cid, "deltas": [{"op": "revise", "key": "k1", "text": "v2"}]},
    )
    body = r.json()
    entry = next(e for e in body["entries"] if e["key"] == "k1")
    assert entry["text"] == "v2"
    assert entry["revision"] == 2

    r2 = client.post(
        "/api/agent-memory/playbooks/workday/apply-deltas",
        json={"campaign_id": cid, "deltas": [{"op": "retire", "key": "k1"}]},
    )
    body2 = r2.json()
    assert body2["entries"] == []
    # Audit trail accumulates all three operations (add, revise, retire).
    assert [a["op"] for a in body2["audit"]] == ["add", "revise", "retire"]


def test_no_op_delta_is_not_recorded_in_applied_or_audit(client):
    cid = _make_campaign(client)
    # Reviving a key that doesn't exist is a no-op per PlaybookService.apply_deltas.
    r = client.post(
        "/api/agent-memory/playbooks/workday/apply-deltas",
        json={"campaign_id": cid, "deltas": [{"op": "revise", "key": "ghost", "text": "x"}]},
    )
    body = r.json()
    assert body["applied"] == []
    assert body["audit"] == []
    assert body["entries"] == []


def test_playbooks_are_isolated_per_ats(client):
    cid = _make_campaign(client)
    client.post(
        "/api/agent-memory/playbooks/workday/apply-deltas",
        json={"campaign_id": cid, "deltas": [{"op": "add", "key": "k", "text": "workday-only"}]},
    )
    other = client.get("/api/agent-memory/playbooks/greenhouse", params={"campaign_id": cid}).json()
    assert other["entries"] == []
    mine = client.get("/api/agent-memory/playbooks/workday", params={"campaign_id": cid}).json()
    assert mine["entries"][0]["text"] == "workday-only"
