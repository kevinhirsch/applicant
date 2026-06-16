"""Phase 2 (part B) service unit tests — sandbox/queue/gate/submission/logging.

Covers the seams Phase 2a left open, with deterministic injected clocks and the
hermetic in-memory adapters (no Neko/Docker/Postgres/network):

* DBOS durable queues: concurrency cap + rate limit + pivot-around-blocker
  (FR-DUR-2/4, FR-AGENT-6) via CapacityService.
* AWAITING_FINAL_APPROVAL gate via durable ``recv`` + escalation ladder
  (FR-NOTIF-2/4, FR-DUR-3) via FinalApprovalService.
* Submission detection + logging + screenshots + conversion capture
  (FR-LOG-1/2/4, FR-LEARN-2) via SubmissionService.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from applicant.adapters.browser.patchright_browser import PatchrightBrowser
from applicant.adapters.notification.apprise_notifier import AppriseNotifier
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.capacity_service import CapacityService
from applicant.application.services.final_approval_service import (
    FinalApprovalService,
    redline_link,
)
from applicant.application.services.notification_service import NotificationService
from applicant.application.services.prefill_service import FINAL_APPROVAL_TOPIC
from applicant.application.services.submission_service import SubmissionService
from applicant.core.entities.application import Application
from applicant.core.entities.outcome_event import OutcomeSource
from applicant.core.ids import ApplicationId, CampaignId, JobPostingId, new_id
from applicant.core.state_machine import ApplicationState


# === CapacityService — concurrency cap + pivot (FR-DUR-2/4, FR-AGENT-6) =====
@pytest.fixture
def orchestrator(tmp_path):
    from applicant.adapters.orchestration.checkpoint_shim import CheckpointShimOrchestrator

    return CheckpointShimOrchestrator(str(tmp_path / "ckpt"))


@pytest.mark.unit
def test_sandbox_concurrency_cap(orchestrator):
    cap = CapacityService(orchestrator, sandbox_concurrency=2)
    assert cap.admit_sandbox("a") is True
    assert cap.admit_sandbox("b") is True
    assert cap.admit_sandbox("c") is False  # cap reached -> c waits


@pytest.mark.unit
def test_pivot_around_blocker(orchestrator):
    # FR-DUR-4 / FR-AGENT-6: a blocked/awaiting app yields capacity to a waiter.
    cap = CapacityService(orchestrator, sandbox_concurrency=1)
    assert cap.admit_sandbox("a") is True
    assert cap.admit_sandbox("b") is False  # b waits behind a
    # 'a' enters AWAITING_FINAL_APPROVAL -> yields its slot; 'b' pivots in.
    promoted = cap.yield_for_block("a", ApplicationState.AWAITING_FINAL_APPROVAL)
    assert promoted == "b"


@pytest.mark.unit
def test_transient_state_does_not_yield(orchestrator):
    cap = CapacityService(orchestrator, sandbox_concurrency=1)
    cap.admit_sandbox("a")
    cap.admit_sandbox("b")
    # PREFILLING is a working state, not a waiting state — no yield/pivot.
    assert cap.yield_for_block("a", ApplicationState.PREFILLING) is None


@pytest.mark.unit
def test_llm_rate_limit(orchestrator):
    cap = CapacityService(orchestrator, sandbox_concurrency=5, llm_limit=2, llm_period=100.0)
    assert cap.admit_llm("c1") is True
    assert cap.admit_llm("c2") is True
    assert cap.admit_llm("c3") is False  # over the per-period limit


# === FinalApprovalService — durable recv gate + ladder (FR-NOTIF-2/4) =======
@pytest.mark.unit
def test_final_approval_gate_durable_recv(orchestrator):
    svc = FinalApprovalService(orchestrator)
    wf = f"app-{new_id()}"
    # No decision yet -> recv returns None (the worker would keep waiting).
    assert svc.await_decision(wf, timeout=0) is None
    svc.submit_decision(wf, "app-1", "finished_by_engine")
    payload = svc.await_decision(wf, timeout=0)
    assert payload == {"decision": "finished_by_engine"}


@pytest.mark.unit
def test_final_approval_uses_topic(orchestrator):
    # The gate must use the same topic the prefill seam pointed at (FR-DUR-3).
    svc = FinalApprovalService(orchestrator)
    wf = f"app-{new_id()}"
    orchestrator.send(wf, FINAL_APPROVAL_TOPIC, {"decision": "submitted_by_user"})
    assert svc.await_decision(wf, timeout=0) == {"decision": "submitted_by_user"}


@pytest.mark.unit
def test_final_approval_escalation_ladder_deterministic():
    # FR-NOTIF-2: Discord held 30s, email after timeout — driven by injected clock.
    clock = {"now": datetime(2026, 1, 1, tzinfo=UTC)}
    notifier = AppriseNotifier(
        discord_webhook_url="https://discord.test/wh",
        apprise_urls="mailto://user:pw@smtp.test",
        clock=lambda: clock["now"],
        email_timeout_seconds=900,
        always_on=True,
    )
    svc = FinalApprovalService(orchestrator=None, notification_service=NotificationService(notifier))
    svc.request_approval("app-1", session_url="https://sandbox.local/neko/s1?token=x")
    # In-app fires immediately; Discord is held.
    assert "in_app" in notifier.sent_channels("decision:final_approval:app-1")
    assert "discord" not in notifier.sent_channels("decision:final_approval:app-1")
    # Advance 30s -> Discord fires.
    clock["now"] += timedelta(seconds=30)
    assert "discord" in svc.escalate(clock["now"])
    # Advance to the email timeout -> email fires.
    clock["now"] += timedelta(seconds=900)
    assert "email" in svc.escalate(clock["now"])


@pytest.mark.unit
def test_final_approval_redline_link_seam():
    # FR-NOTIF-4: review notifications link to the (Phase 3) redline surface.
    assert redline_link("app-1") == "/redline?application=app-1"


@pytest.mark.unit
def test_acted_expires_other_channels():
    notifier = AppriseNotifier(discord_webhook_url="https://discord.test/wh")
    svc = FinalApprovalService(orchestrator=None, notification_service=NotificationService(notifier))
    svc.request_approval("app-1")
    assert notifier.is_active("decision:final_approval:app-1")
    svc.acted("app-1")
    assert not notifier.is_active("decision:final_approval:app-1")


# === SubmissionService — detection + logging + screenshots (FR-LOG-*) =======
def _app(status=ApplicationState.AWAITING_FINAL_APPROVAL) -> Application:
    return Application(
        id=ApplicationId(new_id()),
        campaign_id=CampaignId(new_id()),
        posting_id=JobPostingId(new_id()),
        status=status,
        role_name="Senior Engineer",
        job_title="Senior Engineer",
        work_mode="remote",
        root_url="https://acme.myworkdayjobs.com/job/123",
    )


@pytest.mark.unit
def test_auto_detect_confirmation_page():
    # FR-LOG-4: confirmation-page heuristics detect the final submission.
    browser = PatchrightBrowser()
    aid = ApplicationId(new_id())
    browser.open(aid, "https://acme.myworkdayjobs.com/job/123")
    svc = SubmissionService(InMemoryStorage(), browser)
    assert svc.detect_submission(aid) is False  # account page is not a confirmation
    browser.simulate_confirmation(aid, text="Application submitted. Thank you for applying.")
    assert svc.detect_submission(aid) is True


@pytest.mark.unit
def test_record_submission_logs_detail_and_screenshots():
    storage = InMemoryStorage()
    svc = SubmissionService(storage)
    app = _app()
    event = svc.record_submission(
        app,
        source=OutcomeSource.AUTO,
        attributes_used={"First Name": "Kevin"},
        screenshots=["screenshot://1", "screenshot://2"],
        screenshot_pages=["url/personal", "url/experience"],
    )
    # OutcomeEvent recorded (FR-LEARN-2) ...
    assert event.type == "submitted" and event.source is OutcomeSource.AUTO
    # ... application logged with full detail (FR-LOG-1) ...
    logged = storage.applications.get(app.id)
    assert logged.status is ApplicationState.FINISHED_BY_ENGINE
    assert logged.attributes_used == {"First Name": "Kevin"}
    assert logged.root_url.endswith("/job/123")
    # ... per-page screenshots archived (FR-LOG-2).
    shots = storage.screenshots.list_for_application(app.id)
    assert {s.page_url for s in shots} == {"url/personal", "url/experience"}


@pytest.mark.unit
def test_mark_submitted_is_user_terminal():
    storage = InMemoryStorage()
    svc = SubmissionService(storage)
    app = _app(status=ApplicationState.EMERGENCY_DATA_HANDOFF)
    event = svc.mark_submitted(app)
    assert event.source is OutcomeSource.MANUAL
    assert storage.applications.get(app.id).status is ApplicationState.SUBMITTED_BY_USER


@pytest.mark.unit
def test_get_log_retrieval():
    storage = InMemoryStorage()
    svc = SubmissionService(storage)
    app = _app()
    svc.record_submission(
        app, source=OutcomeSource.AUTO, screenshots=["s://1"], screenshot_pages=["u/1"]
    )
    log = svc.get_log(app.id)
    assert log["role_name"] == "Senior Engineer"
    assert log["work_mode"] == "remote"
    assert len(log["screenshots"]) == 1
    assert log["outcomes"][0]["type"] == "submitted"
