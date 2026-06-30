"""Reachability + campaign-scoping for the Compare router (#297).

Proves the wired endpoint — not just the service class in isolation:
  (a) ``/api/compare/applications`` and ``/api/compare/postings`` are REGISTERED
      routes on the booted app and return non-404 via ``TestClient``;
  (b) a seeded comparison returns real diffs, and an id belonging to a DIFFERENT
      campaign is excluded (campaign scoping — a caller cannot compare across
      campaigns, FR-CRIT-4).

Hermetic: in-memory storage, real container services, LLM gate opened like the
peer router tests.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from applicant.app.main import create_app
from applicant.core.entities.application import Application
from applicant.core.entities.job_posting import JobPosting
from applicant.core.ids import ApplicationId, CampaignId, JobPostingId
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


def _seed_app(container, cid, aid, status=ApplicationState.APPROVED, role="Engineer"):
    container.storage.applications.add(
        Application(
            id=ApplicationId(aid),
            campaign_id=CampaignId(cid),
            posting_id=JobPostingId(f"posting-{aid}"),
            status=status,
            role_name=role,
        )
    )
    container.storage.commit()


def _seed_posting(container, cid, pid, title="Engineer", company="Acme", location="Remote"):
    container.storage.postings.add(
        JobPosting(
            id=JobPostingId(pid),
            campaign_id=CampaignId(cid),
            title=title,
            company=company,
            source_url="https://example.com/job",
            location=location,
        )
    )
    container.storage.commit()


def _registered_paths(app) -> set[str]:
    """All endpoint paths registered on the app.

    This FastAPI build wraps each ``include_router`` in an ``_IncludedRouter`` mount
    whose own ``.path`` is not the endpoint path — the real paths live on its
    ``original_router.routes``. Flatten both levels so registration is observable
    regardless of the mount strategy.
    """
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


# --- (a) reachability: the routes are registered and non-404 -------------------
def test_compare_routes_are_registered(client):
    paths = _registered_paths(client.app)
    assert "/api/compare/applications" in paths
    assert "/api/compare/postings" in paths


def test_compare_endpoints_are_reachable_not_404(client):
    # An empty-body POST exercises dispatch: a real handler responds (200), the
    # missing-mount failure would be 404. Either way it must not be 404.
    r = client.post("/api/compare/applications", json=[])
    assert r.status_code != 404
    r = client.post("/api/compare/postings", json=[])
    assert r.status_code != 404


# --- (b) real diffs through the wired endpoint ---------------------------------
def test_applications_endpoint_returns_real_diffs(client):
    container = client.app.state.container
    cid = "c-1"
    _seed_app(container, cid, "a-1", status=ApplicationState.APPROVED)
    _seed_app(container, cid, "a-2", status=ApplicationState.FINISHED_BY_ENGINE)

    r = client.post(
        "/api/compare/applications",
        params={"campaign_id": cid},
        json=["a-1", "a-2"],
    )
    assert r.status_code == 200
    body = r.json()
    assert set(body["entity_ids"]) == {"a-1", "a-2"}
    status_dim = next(d for d in body["dimensions"] if d["key"] == "status")
    # Two genuinely different statuses surfaced as a diff.
    assert len(set(status_dim["values"].values())) == 2
    assert status_dim["diff"] and "different" in status_dim["diff"]


def test_postings_endpoint_returns_real_diffs(client):
    container = client.app.state.container
    cid = "c-1"
    _seed_posting(container, cid, "p-1", title="Engineer", company="Acme")
    _seed_posting(container, cid, "p-2", title="Manager", company="Beta")

    r = client.post(
        "/api/compare/postings",
        params={"campaign_id": cid},
        json=["p-1", "p-2"],
    )
    assert r.status_code == 200
    body = r.json()
    assert set(body["entity_ids"]) == {"p-1", "p-2"}
    keys = {d["key"] for d in body["dimensions"]}
    assert {"title", "company", "location"} <= keys


# --- (c) campaign scoping: an id from another campaign is excluded --------------
def test_applications_scoping_excludes_other_campaign_id(client):
    container = client.app.state.container
    _seed_app(container, "c-1", "a-1")
    _seed_app(container, "c-1", "a-2")
    _seed_app(container, "c-OTHER", "a-evil")  # different campaign

    r = client.post(
        "/api/compare/applications",
        params={"campaign_id": "c-1"},
        json=["a-1", "a-2", "a-evil"],
    )
    assert r.status_code == 200
    body = r.json()
    # The cross-campaign id is excluded; only the in-campaign pair compares.
    assert set(body["entity_ids"]) == {"a-1", "a-2"}
    assert "a-evil" not in body["entity_ids"]


def test_postings_scoping_excludes_other_campaign_id(client):
    container = client.app.state.container
    _seed_posting(container, "c-1", "p-1")
    _seed_posting(container, "c-1", "p-2")
    _seed_posting(container, "c-OTHER", "p-evil")  # different campaign

    r = client.post(
        "/api/compare/postings",
        params={"campaign_id": "c-1"},
        json=["p-1", "p-2", "p-evil"],
    )
    assert r.status_code == 200
    body = r.json()
    assert set(body["entity_ids"]) == {"p-1", "p-2"}
    assert "p-evil" not in body["entity_ids"]
