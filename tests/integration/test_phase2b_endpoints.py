"""Phase 2 (part B) endpoint integration tests.

Credential vault both ways (FR-VAULT-2), submission detection + log retrieval
(FR-LOG-3/4), and the final-approval gate request (FR-NOTIF-2/4). Default lane is
hermetic (in-memory storage, no Neko/network).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from applicant.app.main import create_app
from applicant.core.ids import new_id


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


def _open_gate(client):
    assert (
        client.post(
            "/api/setup/llm",
            json={"provider": "ollama", "base_url": "http://x/v1", "model": "llama3.1"},
        ).status_code
        == 204
    )


# === Credential vault — both banking modes (FR-VAULT-2) ====================
@pytest.mark.integration
def test_manual_bank_then_list(client):
    _open_gate(client)
    cid = new_id()
    r = client.post(
        "/api/credentials",
        json={"campaign_id": cid, "tenant_key": "acme.workday", "username": "kev", "secret": "s"},
    )
    assert r.status_code == 201 and r.json()["source"] == "manual"
    tenants = client.get(f"/api/credentials/{cid}/tenants").json()["tenants"]
    assert "acme.workday" in tenants


@pytest.mark.integration
def test_capture_hook(client):
    _open_gate(client)
    cid = new_id()
    r = client.post(
        "/api/credentials/capture",
        json={"campaign_id": cid, "tenant_key": "acme.workday", "username": "kev", "secret": "x"},
    )
    assert r.status_code == 201 and r.json()["source"] == "captured"
    # NFR-PRIV-1: the listing endpoint never returns the secret.
    body = client.get(f"/api/credentials/{cid}/tenants").json()
    assert "x" not in str(body)


# === Submission detection + logging + retrieval (FR-LOG-3/4) ===============
@pytest.mark.integration
def test_mark_submitted_then_retrieve_log(client):
    _open_gate(client)
    aid = new_id()
    r = client.post(
        f"/api/outcomes/applications/{aid}/mark-submitted",
        json={"attributes_used": {"First Name": "Kevin"}},
    )
    assert r.status_code == 201 and r.json()["source"] == "manual"
    log = client.get(f"/api/outcomes/applications/{aid}/log").json()
    assert log["status"] == "SUBMITTED_BY_USER"
    assert log["attributes_used"]["First Name"] == "Kevin"
    assert any(o["type"] == "submitted" for o in log["outcomes"])


@pytest.mark.integration
def test_detect_no_session_returns_false(client):
    _open_gate(client)
    aid = new_id()
    # No open browser session for this application -> no auto-detection.
    r = client.post(f"/api/outcomes/applications/{aid}/detect")
    assert r.status_code == 200 and r.json()["detected"] is False


# === Final-approval gate request (FR-NOTIF-2/4) ============================
@pytest.mark.integration
def test_request_final_approval_notifies(client):
    from tests.conftest import open_automated_work_gate

    # /api/remote is automated work behind the automated-work gate (FR-ONBOARD-2).
    open_automated_work_gate(client)
    aid = new_id()
    # Provision a session so the request carries a one-click live-session URL.
    client.post("/api/remote/sessions", json={"application_id": aid})
    r = client.post(f"/api/remote/applications/{aid}/request-final-approval")
    assert r.status_code == 202
    assert r.json()["gate"] == "awaiting"


@pytest.mark.integration
def test_submit_self_logs_and_records(client):
    from tests.conftest import open_automated_work_gate

    open_automated_work_gate(client)
    aid = new_id()
    r = client.post(f"/api/remote/applications/{aid}/submit-self")
    assert r.status_code == 201 and r.json()["result"] == "submitted_by_user"
    log = client.get(f"/api/outcomes/applications/{aid}/log").json()
    assert log["status"] == "SUBMITTED_BY_USER"
