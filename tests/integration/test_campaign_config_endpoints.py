"""Campaign-config endpoint integration tests (#301, FR-CRIT-4 / FR-AGENT-1).

The Settings surface renames / archives / re-tunes a campaign via
``PATCH /api/campaigns/{id}``. Asserts the full config is returned, the engine
clamps the throughput target + exploration budget into their safe ranges
server-side, archive/reactivate flips ``active``, and the reserved system
campaign + unknown ids are refused. Hermetic (in-memory storage, no network).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from applicant.app.main import create_app
from applicant.core.entities.campaign import THROUGHPUT_HARD_CAP
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


def _make_campaign(client) -> str:
    return client.post("/api/campaigns", json={"name": "Backend"}).json()["id"]


def test_create_returns_full_config(client):
    _open_gate(client)
    body = client.post("/api/campaigns", json={"name": "Backend"}).json()
    assert body["name"] == "Backend"
    assert body["run_mode"] == "continuous"
    assert body["active"] is True
    assert "throughput_target" in body and "exploration_budget" in body


def test_patch_renames_and_retunes(client):
    _open_gate(client)
    cid = _make_campaign(client)
    r = client.patch(
        f"/api/campaigns/{cid}",
        json={"name": "Platform", "run_mode": "fixed_duration", "throughput_target": 9},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Platform"
    assert body["run_mode"] == "fixed_duration"
    assert body["throughput_target"] == 9
    # Persisted: re-listing reflects the change.
    listed = {c["id"]: c for c in client.get("/api/campaigns").json()}
    assert listed[cid]["name"] == "Platform"


def test_patch_clamps_throughput_and_budget_server_side(client):
    _open_gate(client)
    cid = _make_campaign(client)
    body = client.patch(
        f"/api/campaigns/{cid}",
        json={"throughput_target": 999, "exploration_budget": 5.0},
    ).json()
    # A caller cannot push past the safety envelope.
    assert body["throughput_target"] == THROUGHPUT_HARD_CAP
    assert body["exploration_budget"] == 1.0


def test_patch_archive_then_reactivate(client):
    _open_gate(client)
    cid = _make_campaign(client)
    assert client.patch(f"/api/campaigns/{cid}", json={"active": False}).json()["active"] is False
    assert client.patch(f"/api/campaigns/{cid}", json={"active": True}).json()["active"] is True


def test_patch_bad_run_mode_is_422(client):
    _open_gate(client)
    cid = _make_campaign(client)
    assert client.patch(f"/api/campaigns/{cid}", json={"run_mode": "teleport"}).status_code == 422


def test_patch_unknown_campaign_is_404(client):
    _open_gate(client)
    assert client.patch(f"/api/campaigns/{new_id()}", json={"name": "ghost"}).status_code == 404


def test_patch_system_campaign_is_refused(client):
    _open_gate(client)
    r = client.patch(f"/api/campaigns/{SYSTEM_CAMPAIGN_ID}", json={"name": "hijack"})
    assert r.status_code == 422


# --- P1-6: cost & pace guardrails --------------------------------------------
def test_guardrails_reports_daily_target_and_hard_cap(client):
    """Daily target (15) + hard cap (30) are surfaced, with no usage yet today."""
    _open_gate(client)
    cid = _make_campaign(client)
    r = client.get(f"/api/campaigns/{cid}/guardrails")
    assert r.status_code == 200
    body = r.json()
    assert body["today"]["daily_target"] == 15
    assert body["today"]["hard_cap"] == THROUGHPUT_HARD_CAP
    assert body["today"]["applications_today"] == 0
    assert body["today"]["usage_reported"] is False
    assert body["today"]["cost_per_application_usd_estimate"] is None
    assert "month_to_date_usd_estimate" in body["monthly"]
    assert "projected_month_usd_estimate" in body["monthly"]


def test_guardrails_reflects_a_retuned_daily_target(client):
    _open_gate(client)
    cid = _make_campaign(client)
    client.patch(f"/api/campaigns/{cid}", json={"throughput_target": 7})
    body = client.get(f"/api/campaigns/{cid}/guardrails").json()
    assert body["today"]["daily_target"] == 7
    assert body["today"]["hard_cap"] == THROUGHPUT_HARD_CAP


def test_guardrails_unknown_campaign_is_404(client):
    _open_gate(client)
    assert client.get(f"/api/campaigns/{new_id()}/guardrails").status_code == 404
