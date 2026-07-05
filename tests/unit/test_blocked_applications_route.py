"""Reachability + real data for the blocked-applications admin routes
(dark-engine audit #61).

Mirrors ``test_stuck_applications_route.py`` (#62)'s shape exactly: hermetic
(in-memory storage via an unreachable DATABASE_URL), real container services,
LLM gate opened like the peer router tests. Proves the two routes are
registered + reachable AND that they read/mutate the SAME process-lived
``container.agent_loop`` (and its injected ``PresubmitBlockLedger``) the
scheduler's tick loop actually uses -- not a disconnected instance.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from applicant.app.main import create_app
from applicant.application.services.presubmit_safety import PresubmitBlock
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


def _seed_blocked_application(
    container, *, title="Backend Engineer", company="Confidential", reason="Placeholder company"
):
    storage = container.storage
    cid = CampaignId(new_id())
    storage.campaigns.add(
        Campaign(id=cid, name="C", run_mode=RunMode.CONTINUOUS, throughput_target=15, schedule={})
    )
    pid = JobPostingId(new_id())
    posting = JobPosting(id=pid, campaign_id=cid, title=title, company=company, source_url="http://x")
    storage.postings.add(posting)
    aid = ApplicationId(new_id())
    app = Application(
        id=aid,
        campaign_id=cid,
        posting_id=pid,
        status=ApplicationState.APPROVED,
        job_title=title,
    )
    storage.applications.add(app)
    loop = container.agent_loop
    assert loop is not None, "container.agent_loop must be wired for this route to do anything"
    exc = PresubmitBlock(reason, check="company_reputation")
    loop._record_presubmit_block(app, posting, exc, datetime.now(UTC))
    return cid, aid


def test_blocked_applications_routes_are_registered(client):
    paths = _registered_paths(client.app)
    assert "/api/admin/blocked-applications/{campaign_id}" in paths
    assert "/api/admin/blocked-applications/{application_id}/override" in paths


def test_blocked_applications_empty_is_well_formed(client):
    r = client.get("/api/admin/blocked-applications/no-such-campaign")
    assert r.status_code == 200
    body = r.json()
    assert body == {
        "campaign_id": "no-such-campaign",
        "applications": [],
        "status": "live",
    }


def test_blocked_applications_lists_real_block_entries_from_the_shared_loop(client):
    # Drive the SAME process-lived AgentLoop instance the route reads from
    # (container.agent_loop) so the response is proven to reflect real ledger
    # state, not a fabricated/hardcoded value.
    container = client.app.state.container
    cid, aid = _seed_blocked_application(
        container, title="Backend Engineer", company="Confidential", reason="Placeholder company"
    )

    r = client.get(f"/api/admin/blocked-applications/{cid}")
    assert r.status_code == 200
    body = r.json()
    assert body["campaign_id"] == str(cid)
    assert len(body["applications"]) == 1
    row = body["applications"][0]
    assert row["application_id"] == str(aid)
    assert row["check"] == "company_reputation"
    assert row["reason"] == "Placeholder company"
    assert row["times_blocked"] == 1
    assert row["job_title"] == "Backend Engineer"
    assert row["company"] == "Confidential"


def test_blocked_applications_scoped_to_the_requested_campaign_only(client):
    container = client.app.state.container
    cid1, aid1 = _seed_blocked_application(container, title="Backend Engineer")
    cid2, aid2 = _seed_blocked_application(container, title="Frontend Engineer")

    r = client.get(f"/api/admin/blocked-applications/{cid1}")
    ids = {row["application_id"] for row in r.json()["applications"]}
    assert ids == {str(aid1)}
    assert str(aid2) not in ids


def test_override_blocked_application_marks_it_via_the_route(client):
    container = client.app.state.container
    _cid, aid = _seed_blocked_application(container)
    loop = container.agent_loop
    assert str(aid) not in loop._presubmit_overridden

    r = client.post(f"/api/admin/blocked-applications/{aid}/override")
    assert r.status_code == 200
    assert r.json() == {"application_id": str(aid), "overridden": True}

    # The SAME shared ledger instance now carries the override -- the very
    # next tick would skip the G07 checks for this application.
    assert str(aid) in loop._presubmit_overridden


def test_override_blocked_application_404s_for_an_application_never_blocked(client):
    r = client.post("/api/admin/blocked-applications/never-blocked/override")
    assert r.status_code == 404
