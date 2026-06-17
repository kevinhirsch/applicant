"""FinalApprovalService — AWAITING_FINAL_APPROVAL gate (FR-NOTIF-2/4, FR-DUR-3).

Wires the §7 ``AWAITING_FINAL_APPROVAL`` waiting state to the durable orchestration
``recv`` gate so a killed worker resumes waiting (FR-DUR-1/3): the gate is a durable
``recv`` on the ``final_approval`` topic, and the user's decision is delivered with
``send`` from the API. While waiting, the **Phase 1 notification escalation ladder**
(FR-NOTIF-2) drives the reminder cadence — Discord held 30s, in-app if present, email
after the configurable timeout — stepped by an **injected clock** so tests are
deterministic.

Document/answer-review notifications link to the (Phase 3) redline surface
(FR-NOTIF-4); the link is built here as a clean seam (``redline_link``) so wiring the
real surface in Phase 3 is a one-line change.
"""

from __future__ import annotations

from applicant.application.services.prefill_service import FINAL_APPROVAL_TOPIC
from applicant.observability.logging import get_logger

log = get_logger(__name__)

#: Decision payload keys delivered via the durable gate.
DECISION_SUBMIT_SELF = "submitted_by_user"
DECISION_ENGINE_FINISH = "finished_by_engine"


def redline_link(application_id: str) -> str:
    """One-click link to the review surface (FR-NOTIF-4).

    #7: returns the SERVED review surface (``/review?application=...``) instead of the
    unserved ``/redline?...`` path, so the notification deep link actually resolves.
    """
    return f"/review?application={application_id}"


class FinalApprovalService:
    def __init__(self, orchestrator, notification_service=None) -> None:
        self._orch = orchestrator
        self._notifications = notification_service

    # --- gate (durable recv, FR-DUR-3) ------------------------------------
    def request_approval(
        self, application_id: str, *, session_url: str | None = None
    ) -> str:
        """Notify the user the application awaits final approval (FR-NOTIF-2/4).

        Fires the escalation ladder via the notification service with a deep link to
        the live session (one-click VNC) and a seam to the redline surface. Returns
        the notification handle.
        """
        ref = f"final_approval:{application_id}"
        if self._notifications is None:
            return ref
        return self._notifications.notify_decision(
            ref,
            title="Final approval / submit",
            body=f"Application {application_id} is ready: review and submit, or authorize the engine.",
            deep_link=session_url or redline_link(application_id),
        )

    def await_decision(self, workflow_id: str, *, timeout: float | None = None):
        """Durably wait for the user's final-approval decision (FR-DUR-3).

        Delegates to the orchestrator's ``recv`` so a crash resumes the wait. Returns
        the decision payload, or ``None`` on timeout (the caller re-notifies via the
        ladder). This is the same gate the ``PrefillService.await_final_approval``
        seam pointed at — now driven end-to-end here.
        """
        return self._orch.recv(workflow_id, FINAL_APPROVAL_TOPIC, timeout=timeout)

    def submit_decision(self, workflow_id: str, application_id: str, decision: str) -> None:
        """Deliver the user's decision to the waiting gate (FR-DUR-3) + expire pings.

        ``decision`` is ``submitted_by_user`` or ``finished_by_engine``. Acting on one
        channel expires the others via the ladder's idempotency (FR-NOTIF-3).
        """
        self._orch.send(workflow_id, FINAL_APPROVAL_TOPIC, {"decision": decision})
        if self._notifications is not None:
            try:
                self._notifications.acted(f"final_approval:{application_id}")
            except Exception:  # ping idempotency must not break decision delivery
                log.warning(
                    "final_approval_decision_notify_failed", application_id=application_id
                )
        log.info("final_approval_decision", application_id=application_id, decision=decision)

    def acted(self, application_id: str) -> None:
        """User acted (submitted / authorized) — expire the other channels (FR-NOTIF-3).

        Guarded: this fires AFTER the submission/conversion is already recorded, so a
        flaky notifier must never 500 an action that already succeeded — it only
        affects reminder idempotency.
        """
        if self._notifications is not None:
            try:
                self._notifications.acted(f"final_approval:{application_id}")
            except Exception:  # notifier failure must not break a recorded submission
                log.warning("final_approval_acted_notify_failed", application_id=application_id)

    def escalate(self, now=None) -> list[str]:
        """Step the escalation ladder (re-notify due rungs) (FR-NOTIF-2).

        Driven by the injected clock so a scheduled tick / a test advances it
        deterministically. Returns the channels fired this tick.
        """
        if self._notifications is None:
            return []
        return self._notifications.advance(now)
