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
    cid = client.post("/api/campaigns", json={"name": "Vault test"}).json()["id"]
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
    cid = client.post("/api/campaigns", json={"name": "Vault test"}).json()["id"]
    r = client.post(
        "/api/credentials/capture",
        json={"campaign_id": cid, "tenant_key": "acme.workday", "username": "kev", "secret": "x"},
    )
    assert r.status_code == 201 and r.json()["source"] == "captured"
    # NFR-PRIV-1: the listing endpoint never returns the secret.
    body = client.get(f"/api/credentials/{cid}/tenants").json()
    assert "x" not in str(body)


@pytest.mark.integration
def test_bank_unknown_campaign_is_404(client):
    """Banking under a campaign that doesn't exist is a clean 404, not a 500 —
    credentials.campaign_id is a NOT-NULL FK to campaigns on a real DB."""
    _open_gate(client)
    r = client.post(
        "/api/credentials",
        json={"campaign_id": new_id(), "tenant_key": "x.workday", "username": "k", "secret": "s"},
    )
    assert r.status_code == 404


@pytest.mark.integration
def test_global_account_credential_bank_and_status(client):
    """Account sign-ins (Google / default new-account set) are global — banked under
    the SYSTEM campaign and reflected in the status endpoint (no secret leaked)."""
    _open_gate(client)
    assert client.get("/api/credentials/account").json() == {
        "google": False,
        "predefined_account": False,
    }
    r = client.post(
        "/api/credentials/account",
        json={"kind": "google", "username": "me@gmail.com", "secret": "g-secret"},
    )
    assert r.status_code == 201 and r.json()["scope"] == "global"
    status = client.get("/api/credentials/account").json()
    assert status["google"] is True and status["predefined_account"] is False
    assert "g-secret" not in str(status)  # NFR-PRIV-1: never returns the secret


@pytest.mark.integration
def test_global_account_credential_rejects_unknown_kind(client):
    _open_gate(client)
    r = client.post(
        "/api/credentials/account",
        json={"kind": "workday:acme", "username": "u", "secret": "s"},
    )
    assert r.status_code == 422


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
def test_submit_self_delivers_decision_through_gate(client):
    """#1: submit-self delivers the decision THROUGH the durable final-approval gate.

    The endpoint no longer records the outcome out-of-band; it ``send``s the decision
    to the workflow's ``recv`` gate so the parked pipeline runs submit/teardown. We
    prove the decision landed in the workflow mailbox and the ladder was expired.
    """
    from applicant.core.entities.application import Application
    from applicant.core.ids import ApplicationId, CampaignId, JobPostingId
    from applicant.core.state_machine import ApplicationState
    from tests.conftest import open_automated_work_gate

    open_automated_work_gate(client)
    container = client.app.state.container
    # Persist a real application parked at the final-approval gate (submit-self now
    # requires the app to exist — a bogus id is a clean 404, not a FK 500).
    aid = ApplicationId(new_id())
    container.storage.applications.add(
        Application(
            id=aid,
            campaign_id=CampaignId(new_id()),
            posting_id=JobPostingId(new_id()),
            status=ApplicationState.AWAITING_FINAL_APPROVAL,
        )
    )
    container.storage.commit()
    r = client.post(f"/api/remote/applications/{aid}/submit-self")
    assert r.status_code == 201 and r.json()["result"] == "submitted_by_user"
    assert r.json()["gate"] == "delivered"
    # The decision was delivered to the durable gate (the pipeline's recv unblocks).
    decision = container.orchestrator.recv(
        f"application:{aid}", "final_approval", timeout=0.0
    )
    assert decision == {"decision": "submitted_by_user"}


# === #4: resume the human account step via a real endpoint ==================
@pytest.mark.integration
def test_resume_account_step_endpoint(client):
    """#4: an app parked at AWAITING_ACCOUNT_HUMAN_STEP is resumed via a real
    endpoint (resume_after_account), continuing the LIVE session rather than orphaning
    it / full-restarting."""
    from applicant.core.entities.application import Application
    from applicant.core.ids import ApplicationId, CampaignId, JobPostingId
    from applicant.core.ids import new_id as nid
    from applicant.core.state_machine import ApplicationState
    from tests.conftest import open_automated_work_gate

    open_automated_work_gate(client)
    container = client.app.state.container
    storage = container.storage
    cid = CampaignId(nid())
    aid = ApplicationId(nid())
    url = "https://acme.myworkdayjobs.com/job/1"
    storage.applications.add(
        Application(
            id=aid,
            campaign_id=cid,
            posting_id=JobPostingId(nid()),
            status=ApplicationState.APPROVED,
            root_url=url,
        )
    )
    storage.commit()
    # Drive pre-fill to the account-creation hand-off (leaves the live session open).
    from applicant.core.entities.attribute import Attribute
    from applicant.core.ids import AttributeId

    def _a(name, value):
        return Attribute(id=AttributeId(nid()), campaign_id=cid, name=name, value=value)

    attrs = [
        _a("Email Address", "kevin@kevinhirsch.com"),
        _a("Password", "S3cretP@ss"),
        _a("Verify Password", "S3cretP@ss"),
        _a("First Name", "Kevin"),
        _a("Last Name", "Hirsch"),
        _a("Phone", "555-0100"),
    ]
    app = storage.applications.get(aid)
    # PrefillService persists where it landed itself; just verify the parked state.
    container.prefill_service.prefill_application(app, url, attrs)
    assert storage.applications.get(aid).status is ApplicationState.AWAITING_ACCOUNT_HUMAN_STEP

    r = client.post(f"/api/remote/applications/{aid}/resume-account-step")
    assert r.status_code == 200
    # The app progressed past the account step (it is no longer awaiting it).
    refreshed = storage.applications.get(aid)
    assert refreshed.status is not ApplicationState.AWAITING_ACCOUNT_HUMAN_STEP

    # Resuming an app NOT at the account step is a 409.
    r2 = client.post(f"/api/remote/applications/{aid}/resume-account-step")
    assert r2.status_code == 409
