"""Reachability + real data for the stuck-applications admin routes
(dark-engine audit #62).

Mirrors ``test_prefill_diagnostics_route.py``'s shape exactly: hermetic
(in-memory storage via an unreachable DATABASE_URL), real container services,
LLM gate opened like the peer router tests. Proves the two routes are
registered + reachable AND that they read/mutate the SAME process-lived
``container.agent_loop`` (and its injected ``ResumeLedger``) the scheduler's
tick loop actually uses -- not a disconnected instance.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from applicant.app.main import create_app
from applicant.application.services.agent_loop import _RESUME_FAILURE_CAP
from applicant.core.entities.application import Application
from applicant.core.entities.campaign import Campaign, RunMode
from applicant.core.entities.job_posting import JobPosting
from applicant.core.ids import ApplicationId, CampaignId, JobPostingId, new_id
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


def _seed_stuck_application(container, *, title="Backend Engineer", company="Acme"):
    storage = container.storage
    cid = CampaignId(new_id())
    storage.campaigns.add(
        Campaign(id=cid, name="C", run_mode=RunMode.CONTINUOUS, throughput_target=15, schedule={})
    )
    pid = JobPostingId(new_id())
    storage.postings.add(
        JobPosting(id=pid, campaign_id=cid, title=title, company=company, source_url="http://x")
    )
    aid = ApplicationId(new_id())
    storage.applications.add(
        Application(
            id=aid,
            campaign_id=cid,
            posting_id=pid,
            status=ApplicationState.BLOCKED_QUESTION,
            role_name=title,
        )
    )
    loop = container.agent_loop
    assert loop is not None, "container.agent_loop must be wired for this route to do anything"
    for _ in range(_RESUME_FAILURE_CAP):
        loop._record_resume_failure(aid)
    return cid, aid


def test_stuck_applications_routes_are_registered(client):
    paths = _registered_paths(client.app)
    assert "/api/admin/stuck-applications/{campaign_id}" in paths
    assert "/api/admin/stuck-applications/{application_id}/retry" in paths


def test_stuck_applications_empty_is_well_formed(client):
    r = client.get("/api/admin/stuck-applications/no-such-campaign")
    assert r.status_code == 200
    body = r.json()
    assert body == {
        "campaign_id": "no-such-campaign",
        "applications": [],
        "status": "live",
    }


def test_stuck_applications_lists_real_giveup_entries_from_the_shared_loop(client):
    # Drive the SAME process-lived AgentLoop instance the route reads from
    # (container.agent_loop) so the response is proven to reflect real ledger
    # state, not a fabricated/hardcoded value.
    container = client.app.state.container
    cid, aid = _seed_stuck_application(container, title="Backend Engineer", company="Acme")

    r = client.get(f"/api/admin/stuck-applications/{cid}")
    assert r.status_code == 200
    body = r.json()
    assert body["campaign_id"] == str(cid)
    assert len(body["applications"]) == 1
    row = body["applications"][0]
    assert row["application_id"] == str(aid)
    assert row["failures"] == _RESUME_FAILURE_CAP
    assert row["job_title"] == "Backend Engineer"
    assert row["company"] == "Acme"


def test_stuck_applications_scoped_to_the_requested_campaign_only(client):
    container = client.app.state.container
    cid1, aid1 = _seed_stuck_application(container, title="Backend Engineer")
    cid2, aid2 = _seed_stuck_application(container, title="Frontend Engineer")

    r = client.get(f"/api/admin/stuck-applications/{cid1}")
    ids = {row["application_id"] for row in r.json()["applications"]}
    assert ids == {str(aid1)}
    assert str(aid2) not in ids


def test_retry_stuck_application_clears_the_flag_via_the_route(client):
    container = client.app.state.container
    _cid, aid = _seed_stuck_application(container)
    loop = container.agent_loop
    assert str(aid) in loop._resume_giveup

    r = client.post(f"/api/admin/stuck-applications/{aid}/retry")
    assert r.status_code == 200
    assert r.json() == {"application_id": str(aid), "retried": True}

    # The SAME shared ledger instance is now clear -- the very next tick would
    # treat this application as resumable again.
    assert str(aid) not in loop._resume_giveup


def test_retry_stuck_application_404s_for_an_application_never_given_up(client):
    r = client.post("/api/admin/stuck-applications/never-stuck/retry")
    assert r.status_code == 404
