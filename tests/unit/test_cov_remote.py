"""Coverage: remote ROUTER (src/applicant/app/routers/remote.py).

Drives the remote-session control surface over HTTP (hermetic: in-memory LocalSandbox,
fake browser). Targets the branches the existing suite leaves uncovered: the index, the
session 404 guard on view-url / takeover, the 503 wrap when sandbox provisioning raises a
non-DomainError, takeover authorization, and the resume-account / resume-detection
endpoints' 404 (unknown app) + 409 (wrong-state) + success paths. The router is behind the
LLM gate; ``request-final-approval`` / submit paths are covered by the integration suite.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from applicant.app.main import create_app
from applicant.core.entities.application import Application
from applicant.core.entities.attribute import Attribute
from applicant.core.ids import (
    ApplicationId,
    AttributeId,
    CampaignId,
    JobPostingId,
    new_id,
)
from applicant.core.state_machine import ApplicationState


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        r = c.post(
            "/api/setup/llm",
            json={"provider": "ollama", "base_url": "http://localhost:11434/v1", "model": "llama3.1"},
        )
        assert r.status_code == 204
        yield c


def test_index(client):
    res = client.get("/api/remote")
    assert res.status_code == 200
    assert res.json() == {"surface": "remote", "phase": 2, "status": "live"}


def test_open_session_then_view_url(client):
    aid = new_id()
    opened = client.post("/api/remote/sessions", json={"application_id": aid})
    assert opened.status_code == 201
    body = opened.json()
    sid = body["session_id"]
    assert body["application_id"] == aid
    assert body["view_url"]

    # view-url for the existing session returns a URL.
    res = client.get(f"/api/remote/sessions/{sid}/view-url")
    assert res.status_code == 200
    assert res.json()["session_id"] == sid
    assert res.json()["view_url"]


def test_view_url_unknown_session_404(client):
    res = client.get("/api/remote/sessions/never-provisioned/view-url")
    assert res.status_code == 404
    assert "Unknown sandbox session" in res.json()["detail"]


def test_takeover_authorizes_existing_session(client):
    aid = new_id()
    sid = client.post("/api/remote/sessions", json={"application_id": aid}).json()["session_id"]
    res = client.post(f"/api/remote/sessions/{sid}/takeover")
    assert res.status_code == 204


def test_takeover_unknown_session_404(client):
    res = client.post("/api/remote/sessions/nope/takeover")
    assert res.status_code == 404


def test_open_session_wraps_provision_failure_as_503(client):
    """A non-DomainError from the sandbox control plane (backend down) is surfaced as a
    503 'unavailable', not a leaked 500 (#11/SECURITY)."""
    container = client.app.state.container

    def _boom(_application_id):
        raise ConnectionError("neko-rooms refused the connection")

    container.sandbox.provision = _boom  # simulate the control plane being down.
    res = client.post("/api/remote/sessions", json={"application_id": new_id()})
    assert res.status_code == 503
    assert "Sandbox provisioning is unavailable" in res.json()["detail"]


def test_open_session_domain_error_propagates_not_503(client):
    """A real rule violation (DomainError) from provisioning is RE-RAISED so the global
    handler maps it (not swallowed into the 503 'unavailable' wrap, which is reserved for
    infra failures like a connection refused)."""
    from applicant.core.errors import InvalidInput

    container = client.app.state.container

    def _rule_violation(_application_id):
        raise InvalidInput("bad application id")

    container.sandbox.provision = _rule_violation
    res = client.post("/api/remote/sessions", json={"application_id": new_id()})
    # InvalidInput maps to 422 via the global handler, NOT the 503 infra wrap.
    assert res.status_code == 422
    assert res.json()["detail"] == "bad application id"


def test_resume_account_step_unknown_application_404(client):
    res = client.post("/api/remote/applications/no-such-app/resume-account-step")
    assert res.status_code == 404
    assert res.json()["detail"] == "Unknown application"


def test_resume_account_step_wrong_state_409(client):
    """An app NOT parked at AWAITING_ACCOUNT_HUMAN_STEP cannot be resumed -> 409."""
    container = client.app.state.container
    storage = container.storage
    aid = ApplicationId(new_id())
    storage.applications.add(
        Application(
            id=aid,
            campaign_id=CampaignId(new_id()),
            posting_id=JobPostingId(new_id()),
            status=ApplicationState.APPROVED,
            root_url="https://acme.example/job/1",
        )
    )
    storage.commit()
    res = client.post(f"/api/remote/applications/{aid}/resume-account-step")
    assert res.status_code == 409
    assert "not awaiting the account step" in res.json()["detail"]


def test_continue_two_factor_unknown_application_404(client):
    res = client.post("/api/remote/applications/no-such-app/continue-two-factor")
    assert res.status_code == 404
    assert res.json()["detail"] == "Unknown application"


def test_continue_two_factor_wrong_state_409(client):
    """The 2FA continue is only valid while the app is held at the account step."""
    container = client.app.state.container
    storage = container.storage
    aid = ApplicationId(new_id())
    storage.applications.add(
        Application(
            id=aid,
            campaign_id=CampaignId(new_id()),
            posting_id=JobPostingId(new_id()),
            status=ApplicationState.APPROVED,
            root_url="https://acme.example/job/2fa",
        )
    )
    storage.commit()
    res = client.post(f"/api/remote/applications/{aid}/continue-two-factor")
    assert res.status_code == 409
    assert "not awaiting the account step" in res.json()["detail"]


def test_resume_detection_step_unknown_application_404(client):
    res = client.post("/api/remote/applications/no-such-app/resume-detection-step")
    assert res.status_code == 404
    assert res.json()["detail"] == "Unknown application"


def test_resume_detection_step_wrong_state_409(client):
    container = client.app.state.container
    storage = container.storage
    aid = ApplicationId(new_id())
    storage.applications.add(
        Application(
            id=aid,
            campaign_id=CampaignId(new_id()),
            posting_id=JobPostingId(new_id()),
            status=ApplicationState.APPROVED,
            root_url="https://acme.example/job/2",
        )
    )
    storage.commit()
    res = client.post(f"/api/remote/applications/{aid}/resume-detection-step")
    assert res.status_code == 409
    assert "not blocked on detection" in res.json()["detail"]


def test_resume_detection_step_success_from_blocked_state(client):
    """An app parked at BLOCKED_DETECTION is resumed via the endpoint (#2, FR-PREFILL-6):
    a legal BLOCKED_DETECTION -> PREFILLING transition, no 404/409."""
    container = client.app.state.container
    storage = container.storage
    cid = CampaignId(new_id())
    aid = ApplicationId(new_id())
    url = "https://acme.example/job/3"
    storage.applications.add(
        Application(
            id=aid,
            campaign_id=cid,
            posting_id=JobPostingId(new_id()),
            status=ApplicationState.BLOCKED_DETECTION,
            root_url=url,
        )
    )
    storage.commit()
    attrs = [
        Attribute(id=AttributeId(new_id()), campaign_id=cid, name="First Name", value="Kevin"),
        Attribute(id=AttributeId(new_id()), campaign_id=cid, name="Last Name", value="Hirsch"),
    ]
    for a in attrs:
        storage.attributes.add(a)
    storage.commit()
    # The user cleared the detection challenge in the LIVE session, so a page is open
    # for this application; resume continues from it (it is NOT re-provisioned).
    container.browser.open(aid, url)

    res = client.post(f"/api/remote/applications/{aid}/resume-detection-step")
    assert res.status_code == 200
    body = res.json()
    assert body["application_id"] == str(aid)
    # The app moved off BLOCKED_DETECTION (it resumed pre-fill).
    assert body["state"] != ApplicationState.BLOCKED_DETECTION.value


def test_router_blocked_before_llm_gate(app):
    with TestClient(app) as c:
        assert c.get("/api/remote").status_code == 409
