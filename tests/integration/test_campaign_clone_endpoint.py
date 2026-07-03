"""Campaign-clone endpoint integration tests (dark-engine audit item 36).

``CampaignService.clone_campaign(source_id, name)`` (#301, FR-CRIT-4) already
duplicates a campaign's criteria/settings under a fresh identity -- it had zero
callers and no router: the natural "same search, new city" move was unreachable.
This pins the new ``POST /api/campaigns/{campaign_id}/clone`` route: it returns
the full duplicated config, defaults the name from the source when none is
supplied, persists the clone alongside the source, and refuses the reserved
system campaign as either a bad id or a clone source. Hermetic (in-memory
storage, no network) -- mirrors ``test_campaign_config_endpoints.py``'s
conventions for this router.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from applicant.app.main import create_app
from applicant.core.ids import SYSTEM_CAMPAIGN_ID, new_id

pytestmark = pytest.mark.integration


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


def _open_gate(client) -> None:
    assert (
        client.post(
            "/api/setup/llm",
            json={"provider": "ollama", "base_url": "http://x/v1", "model": "llama3.1"},
        ).status_code
        == 204
    )


def _make_campaign(client, name: str = "Backend") -> str:
    return client.post("/api/campaigns", json={"name": name}).json()["id"]


def test_clone_returns_full_config_with_new_identity(client):
    _open_gate(client)
    cid = _make_campaign(client, "Backend")
    r = client.post(f"/api/campaigns/{cid}/clone", json={"name": "Backend (Remote)"})
    assert r.status_code == 201
    body = r.json()
    assert body["id"] != cid
    assert body["name"] == "Backend (Remote)"
    assert body["run_mode"] == "continuous"
    assert body["active"] is True


def test_clone_defaults_name_from_source_when_omitted(client):
    _open_gate(client)
    cid = _make_campaign(client, "Backend")
    r = client.post(f"/api/campaigns/{cid}/clone", json={})
    assert r.status_code == 201
    assert r.json()["name"] == "Backend (copy)"


def test_clone_carries_over_retuned_settings(client):
    _open_gate(client)
    cid = _make_campaign(client, "Backend")
    client.patch(
        f"/api/campaigns/{cid}",
        json={"run_mode": "fixed_duration", "throughput_target": 9, "exploration_budget": 0.4},
    )
    r = client.post(f"/api/campaigns/{cid}/clone", json={"name": "Backend clone"})
    body = r.json()
    assert body["run_mode"] == "fixed_duration"
    assert body["throughput_target"] == 9
    assert body["exploration_budget"] == 0.4


def test_clone_persists_alongside_the_source(client):
    _open_gate(client)
    cid = _make_campaign(client, "Backend")
    cloned_id = client.post(f"/api/campaigns/{cid}/clone", json={"name": "Backend II"}).json()["id"]
    listed = {c["id"]: c for c in client.get("/api/campaigns").json()}
    assert cid in listed
    assert cloned_id in listed
    assert listed[cloned_id]["name"] == "Backend II"
    assert listed[cid]["name"] == "Backend"  # source untouched


def test_clone_blank_name_falls_back_to_default_naming(client):
    _open_gate(client)
    cid = _make_campaign(client, "Backend")
    r = client.post(f"/api/campaigns/{cid}/clone", json={"name": "   "})
    assert r.status_code == 201
    assert r.json()["name"] == "Backend (copy)"


def test_clone_unknown_source_is_404(client):
    _open_gate(client)
    r = client.post(f"/api/campaigns/{new_id()}/clone", json={"name": "ghost"})
    assert r.status_code == 404


def test_clone_system_campaign_is_refused(client):
    _open_gate(client)
    r = client.post(f"/api/campaigns/{SYSTEM_CAMPAIGN_ID}/clone", json={"name": "hijack"})
    assert r.status_code == 422
