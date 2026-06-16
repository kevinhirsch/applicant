"""Phase 5 safety-gate enforcement tests.

Each test proves a gate that was previously COMPUTED-BUT-NEVER-ENFORCED is now
enforced. They fail against the pre-fix code and pass after:

* FR-RESUME-8: review-before-submission on the real submit paths (service + HTTP).
* FR-ONBOARD-2 / FR-OOBE-3: automated work blocked until onboarding + channels + LLM.
* FR-FB-1: mandatory non-empty decline feedback.
* FR-ONBOARD-1: onboarding cannot complete without base resume (+ references).
* Digest pending-action key bug: approved/declined digest items leave the portal.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.app.main import create_app
from applicant.application.services.submission_service import SubmissionService
from applicant.core.entities.application import Application
from applicant.core.entities.generated_document import DocumentType, GeneratedDocument
from applicant.core.entities.outcome_event import OutcomeSource
from applicant.core.errors import ReviewRequired
from applicant.core.ids import (
    ApplicationId,
    CampaignId,
    GeneratedDocumentId,
    JobPostingId,
    new_id,
)
from applicant.core.state_machine import ApplicationState
from tests.conftest import open_automated_work_gate


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


def _app() -> Application:
    return Application(
        id=ApplicationId(new_id()),
        campaign_id=CampaignId(new_id()),
        posting_id=JobPostingId(new_id()),
        status=ApplicationState.AWAITING_FINAL_APPROVAL,
        root_url="https://acme.test/job/1",
    )


def _add_doc(storage, app: Application, *, approved: bool) -> GeneratedDocument:
    doc = GeneratedDocument(
        id=GeneratedDocumentId(new_id()),
        campaign_id=app.campaign_id,
        application_id=app.id,
        type=DocumentType.COVER_LETTER,
        content="cover letter body",
        approved=approved,
    )
    storage.documents.add(doc)
    storage.commit()
    return doc


# === FR-RESUME-8 — review-before-submission (service layer) =================
@pytest.mark.unit
def test_fr_resume_8_record_submission_blocks_unapproved_material():
    """FR-RESUME-8: record_submission refuses to submit unapproved generated material."""
    storage = InMemoryStorage()
    svc = SubmissionService(storage)
    app = _app()
    _add_doc(storage, app, approved=False)
    with pytest.raises(ReviewRequired):
        svc.record_submission(app, source=OutcomeSource.AUTO)


@pytest.mark.unit
def test_fr_resume_8_mark_submitted_blocks_unapproved_material():
    """FR-RESUME-8: the one-tap mark-submitted path is gated too."""
    storage = InMemoryStorage()
    svc = SubmissionService(storage)
    app = _app()
    _add_doc(storage, app, approved=False)
    with pytest.raises(ReviewRequired):
        svc.mark_submitted(app)


@pytest.mark.unit
def test_fr_resume_8_approved_material_can_submit():
    """FR-RESUME-8: with all generated material approved, submission proceeds."""
    storage = InMemoryStorage()
    svc = SubmissionService(storage)
    app = _app()
    _add_doc(storage, app, approved=True)
    event = svc.record_submission(app, source=OutcomeSource.AUTO)
    assert event.type == "submitted"


# === FR-RESUME-8 — review-before-submission (HTTP submit paths) =============
@pytest.mark.integration
def test_fr_resume_8_outcomes_mark_submitted_409_when_unapproved(client):
    open_automated_work_gate(client)
    storage = client.app.state.container.storage
    app = _app()
    storage.applications.add(app)
    _add_doc(storage, app, approved=False)
    r = client.post(f"/api/outcomes/applications/{app.id}/mark-submitted")
    assert r.status_code == 409


@pytest.mark.integration
def test_fr_resume_8_remote_submit_self_409_when_unapproved(client):
    open_automated_work_gate(client)
    storage = client.app.state.container.storage
    app = _app()
    storage.applications.add(app)
    _add_doc(storage, app, approved=False)
    r = client.post(f"/api/remote/applications/{app.id}/submit-self")
    assert r.status_code == 409


@pytest.mark.integration
def test_fr_resume_8_remote_engine_finish_409_when_unapproved(client):
    open_automated_work_gate(client)
    storage = client.app.state.container.storage
    app = _app()
    storage.applications.add(app)
    _add_doc(storage, app, approved=False)
    r = client.post(f"/api/remote/applications/{app.id}/authorize-engine-finish")
    assert r.status_code == 409


@pytest.mark.integration
def test_fr_resume_8_outcomes_mark_submitted_ok_when_approved(client):
    open_automated_work_gate(client)
    storage = client.app.state.container.storage
    app = _app()
    storage.applications.add(app)
    _add_doc(storage, app, approved=True)
    r = client.post(f"/api/outcomes/applications/{app.id}/mark-submitted")
    assert r.status_code == 201


# === FR-ONBOARD-2 / FR-OOBE-3 — automated-work gate ========================
def _open_llm_only(client) -> None:
    r = client.post(
        "/api/setup/llm",
        json={"provider": "ollama", "base_url": "http://x/v1", "model": "llama3.1"},
    )
    assert r.status_code == 204


@pytest.mark.integration
def test_fr_onboard_2_automated_work_blocked_until_all_gates(client):
    """FR-ONBOARD-2/FR-OOBE-3: agent-runs config 409s until onboarding+channels+LLM."""
    cid = new_id()
    # Nothing configured: blocked.
    r = client.put(f"/api/agent-runs/{cid}/config", json={"throughput_target": 5})
    assert r.status_code == 409
    # LLM only: still blocked (channels + onboarding missing).
    _open_llm_only(client)
    r = client.put(f"/api/agent-runs/{cid}/config", json={"throughput_target": 5})
    assert r.status_code == 409
    # LLM + channels but onboarding still incomplete: blocked.
    assert (
        client.post(
            "/api/setup/channels", json={"discord_webhook_url": "https://discord.test/wh"}
        ).status_code
        == 204
    )
    r = client.put(f"/api/agent-runs/{cid}/config", json={"throughput_target": 5})
    assert r.status_code == 409
    # Complete onboarding too: now allowed (create the campaign so config can persist).
    client.app.state.container.setup_service._onboarding_gate = lambda: True
    cid = client.post("/api/campaigns", json={"name": "gate"}).json()["id"]
    r = client.put(f"/api/agent-runs/{cid}/config", json={"throughput_target": 5})
    assert r.status_code == 200


@pytest.mark.integration
def test_fr_onboard_2_digest_build_blocked_until_gate_open(client):
    cid = new_id()
    _open_llm_only(client)
    # LLM open but automated-work gate closed -> 409.
    assert client.get(f"/api/digest/{cid}").status_code == 409
    open_automated_work_gate(client)
    assert client.get(f"/api/digest/{cid}").status_code == 200


# === FR-FB-1 — mandatory non-empty decline feedback ========================
@pytest.mark.integration
def test_fr_fb_1_blank_decline_feedback_rejected(client):
    open_automated_work_gate(client)
    aid = new_id()
    # Blank/whitespace feedback rejected with 422.
    r = client.post(
        f"/api/digest/applications/{aid}/decline", json={"feedback_text": "   "}
    )
    assert r.status_code == 422
    # Empty string rejected too.
    r = client.post(f"/api/digest/applications/{aid}/decline", json={"feedback_text": ""})
    assert r.status_code == 422
    # Non-empty feedback accepted.
    r = client.post(
        f"/api/digest/applications/{aid}/decline", json={"feedback_text": "too junior"}
    )
    assert r.status_code == 201


# === Digest pending-action key bug — approved item leaves the portal =======
@pytest.mark.unit
def test_digest_approval_resolves_pending_action_by_posting_id():
    """An approved/declined digest item is removed from the pending-actions portal.

    Regression: deliver materialized the pending action keyed on posting_id but the
    resolve path keyed on application_id, so the portal item leaked.
    """
    from applicant.adapters.notification.apprise_notifier import AppriseNotifier
    from applicant.application.services.digest_service import DigestService
    from applicant.application.services.notification_service import NotificationService
    from applicant.application.services.pending_actions_service import PendingActionsService
    from applicant.core.entities.campaign import Campaign
    from applicant.core.entities.job_posting import JobPosting

    storage = InMemoryStorage()
    cid = CampaignId(new_id())
    storage.campaigns.add(Campaign(id=cid, name="c"))
    posting = JobPosting(
        id=JobPostingId(new_id()),
        campaign_id=cid,
        title="Senior Engineer",
        company="Acme",
        source_url="https://acme.test/job",
        work_mode="remote",
        description="python",
        source_key="jobspy:indeed",
    )
    storage.postings.add(posting)
    storage.commit()

    notifier = AppriseNotifier(discord_webhook_url="https://discord.test/wh")
    pending = PendingActionsService(storage)
    digest = DigestService(
        storage,
        notifier,
        scoring=None,
        notification_service=NotificationService(notifier),
        pending_actions=pending,
    )
    digest.deliver(cid)
    assert any(a.kind == "digest_approval" for a in pending.list_pending(cid))

    # Approve by the digest-row id (the posting id) -> the pending item resolves.
    digest.approve(ApplicationId(str(posting.id)))
    assert not any(a.kind == "digest_approval" for a in pending.list_pending(cid))
