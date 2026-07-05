"""Reachability + real data for the ``/api/admin/resume-status/{id}`` (#78) and
``/api/admin/research-provenance/{id}`` (#76) routes.

Mirrors ``test_stuck_applications_route.py``'s shape: hermetic (in-memory
storage via an unreachable DATABASE_URL), real container services, LLM gate
opened like the peer router tests. Proves both routes are registered +
reachable AND that they read the SAME process-lived ``container.agent_loop``
ResumeLedger / orchestrator checkpoint the scheduler's tick loop actually uses
-- not a disconnected instance.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from applicant.app.main import create_app
from applicant.core.entities.application import Application
from applicant.core.ids import ApplicationId, CampaignId, new_id
from applicant.core.state_machine import ApplicationState


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        r = c.post(
            "/api/setup/llm",
            json={"provider": "ollama", "base_url": "http://localhost:11434/v1", "model": "llama3.1"},
        )
        assert r.status_code == 204
        yield c


def _registered_paths(app) -> set[str]:
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


def _seed_blocked_application(container, status: ApplicationState) -> tuple[CampaignId, ApplicationId]:
    storage = container.storage
    cid = CampaignId(new_id())
    aid = ApplicationId(new_id())
    storage.applications.add(
        Application(
            id=aid,
            campaign_id=cid,
            posting_id=None,
            status=status,
            role_name="Senior Engineer",
        )
    )
    storage.commit()
    return cid, aid


def test_resume_and_research_routes_are_registered(client):
    paths = _registered_paths(client.app)
    assert "/api/admin/resume-status/{application_id}" in paths
    assert "/api/admin/research-provenance/{application_id}" in paths


# --- #78: resume-status ------------------------------------------------------


def test_resume_status_not_blocked_for_unknown_application(client):
    r = client.get("/api/admin/resume-status/no-such-application")
    assert r.status_code == 200
    assert r.json() == {"application_id": "no-such-application", "status": "not_blocked"}


def test_resume_status_reports_a_real_countdown_from_the_shared_loop(client):
    container = client.app.state.container
    cid, aid = _seed_blocked_application(container, ApplicationState.BLOCKED_QUESTION)
    loop = container.agent_loop
    assert loop is not None, "container.agent_loop must be wired for this route to do anything"
    now = datetime(2026, 6, 16, 12, 0, 0, tzinfo=UTC)
    loop._mark_resumed(aid, now)

    r = client.get(f"/api/admin/resume-status/{aid}")
    assert r.status_code == 200
    body = r.json()
    assert body["application_id"] == str(aid)
    assert body["status"] == "BLOCKED_QUESTION"
    assert body["last_resume_at"] == now.isoformat()
    assert "next_retry_at" in body
    assert "seconds_remaining" in body


def test_resume_status_not_blocked_when_application_never_resumed(client):
    container = client.app.state.container
    _cid, aid = _seed_blocked_application(container, ApplicationState.BLOCKED_MISSING_ATTR)
    r = client.get(f"/api/admin/resume-status/{aid}")
    assert r.status_code == 200
    assert r.json() == {"application_id": str(aid), "status": "not_blocked"}


# --- #76: research-provenance -------------------------------------------------


def test_research_provenance_used_false_when_never_researched(client):
    container = client.app.state.container
    _cid, aid = _seed_blocked_application(container, ApplicationState.MATERIAL_REVIEW)
    r = client.get(f"/api/admin/research-provenance/{aid}")
    assert r.status_code == 200
    assert r.json() == {"application_id": str(aid), "used": False}


def test_research_provenance_surfaces_a_real_checkpointed_report(client):
    container = client.app.state.container
    _cid, aid = _seed_blocked_application(container, ApplicationState.MATERIAL_REVIEW)
    orch = container.orchestrator
    workflow_id = f"application:{aid}"
    provenance = {"company": "Acme Corp", "summary_excerpt": "...", "sources": []}
    orch.run_step(
        workflow_id, "material", lambda: {"research_used": True, "research_provenance": provenance}
    )

    r = client.get(f"/api/admin/research-provenance/{aid}")
    assert r.status_code == 200
    body = r.json()
    assert body["application_id"] == str(aid)
    assert body["used"] is True
    assert body["company"] == "Acme Corp"
