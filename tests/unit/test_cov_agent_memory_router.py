"""Coverage: the agent-memory router (FR-MIND-1/2/9/12).

Exercises GET /api/agent-memory (curated snapshot), /skills (saved playbooks), and
the curation queue (list + approve/deny) against the real container services with
the default in_memory backend. Hermetic: in-memory storage, real services.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from applicant.app.main import create_app
from applicant.application.services.curation_service import RunSummary, proposal_to_dict
from applicant.ports.driven.memory_store import KIND_USER, MemoryEntry
from applicant.ports.driven.skill_store import Skill


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        r = c.post(
            "/api/setup/llm",
            json={"provider": "ollama", "base_url": "http://localhost:11434/v1", "model": "llama3.1"},
        )
        assert r.status_code == 204
        yield c


def test_gated_until_llm_configured():
    # Without the LLM gate open, the surface 409s (FR-UI-5).
    with TestClient(create_app()) as c:
        assert c.get("/api/agent-memory").status_code == 409


def test_memory_snapshot_splits_kinds(client):
    mem = client.app.state.container.agent_memory.memory
    mem.add(MemoryEntry(text="Acme uses Workday", kind="environment"))
    mem.add(MemoryEntry(text="Prefers concise letters", kind=KIND_USER))

    body = client.get("/api/agent-memory").json()
    assert any("Workday" in e["text"] for e in body["environment"])
    assert any("concise" in e["text"] for e in body["user"])


def test_skills_list_and_load(client):
    skills = client.app.state.container.agent_memory.skills
    skills.create(Skill(name="acme-flow", description="Acme tenant", procedure=("log in",)))

    listed = client.get("/api/agent-memory/skills").json()
    assert listed["items"][0]["name"] == "acme-flow"
    got = client.get("/api/agent-memory/skills/acme-flow").json()
    assert got["procedure"] == ["log in"]
    assert client.get("/api/agent-memory/skills/nope").status_code == 404


def test_curation_list_approve_and_deny(client):
    container = client.app.state.container
    curation = container.curation_service
    mem = container.agent_memory.memory
    # Stage proposals via a real curation tick (review-before-write default on).
    curation.run_curation_tick(
        [RunSummary(run_id="run-1", campaign_id=None, text="A keepable lesson.", tool_calls=1, topic="t1")]
    )
    listed = client.get("/api/agent-memory/curation").json()
    assert listed["count"] == 1
    pid = listed["items"][0]["id"]

    # Approve applies it to the durable store and clears it.
    assert client.post(f"/api/agent-memory/curation/{pid}/approve").json()["ok"] is True
    assert any("keepable" in e.text for e in mem.snapshot().all())
    # Approving again -> 404 (already handled).
    assert client.post(f"/api/agent-memory/curation/{pid}/approve").status_code == 404

    # Deny path: stage another, then deny it (nothing applied).
    curation.run_curation_tick(
        [RunSummary(run_id="run-2", campaign_id=None, text="Another keepable lesson.", tool_calls=1, topic="t2")]
    )
    pid2 = proposal_to_dict(curation.list_staged()[0])["id"]
    assert client.post(f"/api/agent-memory/curation/{pid2}/deny").json()["ok"] is True
    assert curation.list_staged() == ()


def test_snapshot_entries_carry_stable_refs(client):
    mem = client.app.state.container.agent_memory.memory
    mem.add(MemoryEntry(text="Acme uses Workday", kind="environment"))
    body = client.get("/api/agent-memory").json()
    refs = [e["ref"] for e in body["environment"] if "Workday" in e["text"]]
    assert refs and refs[0]
    # Stable: a second read yields the same ref for the same line.
    body2 = client.get("/api/agent-memory").json()
    refs2 = [e["ref"] for e in body2["environment"] if "Workday" in e["text"]]
    assert refs == refs2


def test_forget_stages_for_review_by_default(client):
    container = client.app.state.container
    mem = container.agent_memory.memory
    mem.add(MemoryEntry(text="Forget me please", kind="environment"))
    ref = next(
        e["ref"] for e in client.get("/api/agent-memory").json()["environment"]
        if "Forget me" in e["text"]
    )
    # Default posture is review-on (FR-MIND-9): a forget is STAGED, not applied.
    r = client.post("/api/agent-memory/forget", json={"ref": ref})
    assert r.status_code == 200
    body = r.json()
    assert body["staged"] == 1 and body["applied"] == 0
    # Still remembered until approval.
    assert any("Forget me" in e.text for e in mem.snapshot().all())
    # It shows up in the review queue as a forget proposal, and approving removes it.
    queued = client.get("/api/agent-memory/curation").json()["items"]
    forget = next(p for p in queued if p["type"] == "forget")
    assert client.post(f"/api/agent-memory/curation/{forget['id']}/approve").json()["ok"] is True
    assert not any("Forget me" in e.text for e in mem.snapshot().all())


def test_forget_applies_immediately_when_approval_relaxed(client):
    container = client.app.state.container
    mem = container.agent_memory.memory
    container.curation_service._memory_write_approval = False
    mem.add(MemoryEntry(text="Drop this now", kind="user"))
    ref = next(
        e["ref"] for e in client.get("/api/agent-memory").json()["user"]
        if "Drop this" in e["text"]
    )
    r = client.post("/api/agent-memory/forget", json={"ref": ref})
    assert r.json()["applied"] == 1 and r.json()["staged"] == 0
    assert not any("Drop this" in e.text for e in mem.snapshot().all())


def test_forget_requires_a_target(client):
    assert client.post("/api/agent-memory/forget", json={}).status_code == 400
