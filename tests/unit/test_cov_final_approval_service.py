"""FinalApprovalService coverage (FR-NOTIF-2/4, FR-DUR-3).

Targets the durable-gate seam (recv/send delegated to the orchestrator), the
notification escalation ladder, and — critically — the guarded notifier paths:
a flaky notifier must NEVER break a decision/submission that already succeeded
(FR-NOTIF-3). Hermetic: fake orchestrator + fake notification service.
"""

from __future__ import annotations

from applicant.application.services.final_approval_service import (
    DECISION_SUBMIT_SELF,
    FinalApprovalService,
    redline_link,
)
from applicant.application.services.prefill_service import FINAL_APPROVAL_TOPIC


class _FakeOrch:
    """Records send/recv against the durable gate."""

    def __init__(self, recv_value=None) -> None:
        self.sent: list[tuple] = []
        self.recv_calls: list[tuple] = []
        self._recv_value = recv_value

    def send(self, workflow_id, topic, payload):
        self.sent.append((workflow_id, topic, payload))

    def recv(self, workflow_id, topic, *, timeout=None):
        self.recv_calls.append((workflow_id, topic, timeout))
        return self._recv_value


class _FakeNotifications:
    def __init__(self, *, fail_on=()) -> None:
        self.notify_decision_calls: list[dict] = []
        self.acted_calls: list[str] = []
        self.advance_calls: list = []
        self._fail_on = set(fail_on)
        self.advance_result = ["discord"]

    def notify_decision(self, ref, *, title, body, deep_link):
        self.notify_decision_calls.append(
            {"ref": ref, "title": title, "body": body, "deep_link": deep_link}
        )
        return f"handle:{ref}"

    def acted(self, ref):
        self.acted_calls.append(ref)
        if "acted" in self._fail_on:
            raise RuntimeError("notifier down")

    def advance(self, now):
        self.advance_calls.append(now)
        return self.advance_result


# === redline link (FR-NOTIF-4, #7) =========================================
def test_redline_link_points_at_served_review_surface():
    assert redline_link("app-123") == "/review?application=app-123"


# === request_approval ======================================================
def test_request_approval_without_notifications_returns_ref():
    svc = FinalApprovalService(_FakeOrch(), notification_service=None)
    assert svc.request_approval("app-1") == "final_approval:app-1"


def test_request_approval_uses_session_url_as_deep_link():
    notifs = _FakeNotifications()
    svc = FinalApprovalService(_FakeOrch(), notification_service=notifs)
    handle = svc.request_approval("app-9", session_url="https://vnc.test/session")
    assert handle == "handle:final_approval:app-9"
    call = notifs.notify_decision_calls[0]
    assert call["deep_link"] == "https://vnc.test/session"  # live session wins
    assert "app-9" in call["body"]


def test_request_approval_falls_back_to_redline_link():
    notifs = _FakeNotifications()
    svc = FinalApprovalService(_FakeOrch(), notification_service=notifs)
    svc.request_approval("app-7")  # no session_url -> redline link
    assert notifs.notify_decision_calls[0]["deep_link"] == "/review?application=app-7"


# === await_decision (durable recv, FR-DUR-3) ===============================
def test_await_decision_delegates_to_orchestrator_recv():
    orch = _FakeOrch(recv_value={"decision": "submitted_by_user"})
    svc = FinalApprovalService(orch)
    result = svc.await_decision("wf-1", timeout=5.0)
    assert result == {"decision": "submitted_by_user"}
    assert orch.recv_calls == [("wf-1", FINAL_APPROVAL_TOPIC, 5.0)]


# === submit_decision (send + expire pings) ================================
def test_submit_decision_sends_to_gate_and_expires_pings():
    orch = _FakeOrch()
    notifs = _FakeNotifications()
    svc = FinalApprovalService(orch, notification_service=notifs)
    svc.submit_decision("wf-2", "app-2", DECISION_SUBMIT_SELF)
    # The decision is delivered to the durable gate on the right topic.
    assert orch.sent == [("wf-2", FINAL_APPROVAL_TOPIC, {"decision": DECISION_SUBMIT_SELF})]
    # And the other channels are expired via the ladder.
    assert notifs.acted_calls == ["final_approval:app-2"]


def test_submit_decision_swallows_notifier_failure():
    # A flaky notifier must NOT break decision delivery (the send already happened).
    orch = _FakeOrch()
    notifs = _FakeNotifications(fail_on=("acted",))
    svc = FinalApprovalService(orch, notification_service=notifs)
    svc.submit_decision("wf-3", "app-3", DECISION_SUBMIT_SELF)  # must not raise
    assert orch.sent  # the durable send still landed


def test_submit_decision_without_notifications_still_sends():
    orch = _FakeOrch()
    svc = FinalApprovalService(orch, notification_service=None)
    svc.submit_decision("wf-4", "app-4", DECISION_SUBMIT_SELF)
    assert orch.sent


# === acted (idempotency, FR-NOTIF-3) ======================================
def test_acted_expires_channels():
    notifs = _FakeNotifications()
    svc = FinalApprovalService(_FakeOrch(), notification_service=notifs)
    svc.acted("app-5")
    assert notifs.acted_calls == ["final_approval:app-5"]


def test_acted_swallows_notifier_failure():
    # A recorded submission must never 500 because the reminder expiry failed.
    notifs = _FakeNotifications(fail_on=("acted",))
    svc = FinalApprovalService(_FakeOrch(), notification_service=notifs)
    svc.acted("app-6")  # must not raise


def test_acted_no_op_without_notifications():
    svc = FinalApprovalService(_FakeOrch(), notification_service=None)
    svc.acted("app-x")  # no notifier wired -> simply nothing happens


# === escalate (ladder tick, FR-NOTIF-2) ===================================
def test_escalate_advances_ladder_and_returns_fired_channels():
    notifs = _FakeNotifications()
    svc = FinalApprovalService(_FakeOrch(), notification_service=notifs)
    fired = svc.escalate(now="2026-06-17T00:00:00Z")
    assert fired == ["discord"]
    assert notifs.advance_calls == ["2026-06-17T00:00:00Z"]


def test_escalate_returns_empty_without_notifications():
    svc = FinalApprovalService(_FakeOrch(), notification_service=None)
    assert svc.escalate() == []
