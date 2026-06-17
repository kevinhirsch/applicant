"""Coverage: discovery-sources ROUTER (src/applicant/app/routers/discovery_sources.py).

Drives the two endpoints over HTTP against the in-process app (hermetic: offline fake
discovery clients by default): the GET listing (which syncs the registry then returns the
per-campaign source toggles + learned yield stats) and the PUT toggle (which persists a
source enable/disable). Also asserts the two gates the router declares: it 409s before the
LLM gate AND before the automated-work gate are open.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from applicant.app.main import create_app
from tests.conftest import open_automated_work_gate


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
def gated_client(app):
    """A client with BOTH the LLM gate and the automated-work gate open."""
    with TestClient(app) as c:
        open_automated_work_gate(c)
        yield c


def test_list_sources_syncs_registry_and_returns_toggles(gated_client):
    cid = "camp-disc-1"
    res = gated_client.get(f"/api/discovery-sources/{cid}")
    assert res.status_code == 200
    body = res.json()
    assert body["campaign_id"] == cid
    # sync_registry seeded the adapter's available sources, enabled by default.
    assert len(body["items"]) > 0
    item = body["items"][0]
    assert set(item) == {"source_key", "enabled", "yield_stats"}
    assert item["enabled"] is True


def test_toggle_source_persists_disable_then_reflects_in_list(gated_client):
    cid = "camp-disc-2"
    listing = gated_client.get(f"/api/discovery-sources/{cid}").json()
    key = listing["items"][0]["source_key"]

    # Disable the source via PUT.
    res = gated_client.put(
        f"/api/discovery-sources/{cid}/{key}", json={"enabled": False}
    )
    assert res.status_code == 200
    assert res.json() == {"campaign_id": cid, "source_key": key, "enabled": False}

    # The disable persisted: the source now reports enabled=False in the listing.
    after = gated_client.get(f"/api/discovery-sources/{cid}").json()
    toggled = next(i for i in after["items"] if i["source_key"] == key)
    assert toggled["enabled"] is False

    # Re-enabling flips it back (real persisted toggle).
    gated_client.put(f"/api/discovery-sources/{cid}/{key}", json={"enabled": True})
    again = gated_client.get(f"/api/discovery-sources/{cid}").json()
    assert next(i for i in again["items"] if i["source_key"] == key)["enabled"] is True


def test_toggle_requires_enabled_field(gated_client):
    # The ToggleSourceIn body requires ``enabled``; omitting it is a 422.
    res = gated_client.put("/api/discovery-sources/camp-x/some-source", json={})
    assert res.status_code == 422


def test_router_blocked_before_llm_gate(app):
    # No gates opened: the LLM gate 409s before automated-work is even checked.
    with TestClient(app) as c:
        res = c.get("/api/discovery-sources/camp-z")
        assert res.status_code == 409


def test_router_blocked_before_automated_work_gate(app):
    # Open ONLY the LLM gate; the automated-work gate must still block the router.
    with TestClient(app) as c:
        r = c.post(
            "/api/setup/llm",
            json={"provider": "ollama", "base_url": "http://localhost:11434/v1", "model": "llama3.1"},
        )
        assert r.status_code == 204
        res = c.get("/api/discovery-sources/camp-z")
        assert res.status_code == 409
        assert "Automated work is blocked" in res.json()["detail"]
