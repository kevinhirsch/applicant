"""Regression coverage for exhaustive2 lens-10 audit findings #2/#3.

Anchor: docs/design/audits/exhaustive2/10_notifications.md

#2 — "Cautious-mode detection pause pings a method that doesn't exist." The
cautious-mode / blocked-detection hand-off (FR-PREFILL-6, both the non-planner
``_blocked_detection`` path and the planner-path ``blocked_detection`` StopOp
site) must call the REAL ``NotificationPort.notify(...)`` method — not a
``notify_pending(...)`` that no class implements (which the old code swallowed
via ``try/except: pass``, so the human never heard about the one moment the
spec flags as needing them).

#3 — "CRITICAL urgency is renderable-but-never-emitted." The port's
``NotificationUrgency.CRITICAL`` exists precisely so a live hand-off (CAPTCHA /
takeover / detection block) is NEVER deferred by quiet hours. Both cautious-
pause sites must emit CRITICAL, not the default NORMAL.

This file adds NEW tests only; it does not modify the existing, more
exhaustive coverage in ``tests/unit/test_prefill_service.py``
(``TestCautiousModeDetectionNotification`` / ``TestNotificationUrgencyScoping``).
Hand-verified RED-on-revert / GREEN-on-restore against a temporarily reverted
copy of ``prefill_service.py`` (see task notes) — not committed here.
"""

from __future__ import annotations

import pytest

from applicant.adapters.browser.patchright_browser import PatchrightBrowser
from applicant.adapters.detection.detection_monitor import DetectionMonitor
from applicant.adapters.sandbox.local_sandbox import LocalSandbox
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.prefill_service import PrefillResult, PrefillService
from applicant.core.entities.application import Application
from applicant.core.entities.detection_event import DetectionEvent
from applicant.core.entities.plan import Plan, StopOp
from applicant.core.ids import (
    ApplicationId,
    CampaignId,
    DetectionEventId,
    JobPostingId,
    new_id,
)
from applicant.core.state_machine import ApplicationState
from applicant.ports.driven.browser_automation import PageState
from applicant.ports.driven.notification import Notification, NotificationUrgency

WORKDAY_URL = "https://acme.myworkdayjobs.com/job/123"


def _app(cid):
    return Application(
        id=ApplicationId(new_id()),
        campaign_id=cid,
        posting_id=JobPostingId(new_id()),
        status=ApplicationState.APPROVED,
        root_url=WORKDAY_URL,
    )


class _NotifySpy:
    """Minimal spy implementing ONLY the real NotificationPort surface.

    If a call site regresses to a nonexistent ``notify_pending(...)`` this
    spy has no such attribute, so the call raises ``AttributeError`` — these
    sites do not swallow that (unlike the unrelated, already-tracked
    ``post_submission_service`` dead path), so the test fails loudly.
    """

    def __init__(self):
        self.calls: list[Notification] = []

    def notify(self, notification):
        self.calls.append(notification)
        return "handle"

    def expire(self, dedup_key):
        pass

    def is_configured(self):
        return True


def _service(storage, notification):
    return PrefillService(
        storage=storage,
        browser=PatchrightBrowser(),
        detection=DetectionMonitor(),
        sandbox=LocalSandbox(),
        credentials=None,
        notification=notification,
    )


@pytest.mark.unit
class TestBlockedDetectionCallsRealNotifyMethod:
    """#2: the cautious-mode pause must notify via the real port method."""

    def test_non_planner_blocked_detection_calls_notify_not_notify_pending(self):
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        spy = _NotifySpy()
        service = _service(storage, spy)
        app = _app(cid).with_status(ApplicationState.SANDBOX_PROVISIONING).with_status(
            ApplicationState.PREFILLING
        )
        result = PrefillResult(application_id=app.id, state=app.status)
        event = DetectionEvent(
            id=DetectionEventId(new_id()),
            application_id=app.id,
            signal_type="cloudflare",
        )

        outcome = service._blocked_detection(app, result, event)

        assert outcome.state == ApplicationState.BLOCKED_DETECTION
        # The fix routes through the real `notify()` — this call landing in the
        # spy at all is the regression signal: the old `notify_pending(...)`
        # call would AttributeError against this spy (no try/except at this
        # call site would hide it) or silently vanish behind the swallow.
        assert len(spy.calls) == 1
        assert isinstance(spy.calls[0], Notification)

    def test_planner_path_blocked_detection_calls_notify_not_notify_pending(self):
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        spy = _NotifySpy()
        service = _service(storage, spy)
        app = _app(cid)
        state = PageState(url=f"{WORKDAY_URL}/apply", fields=())
        plan = Plan(ops=(StopOp(reason="captcha"),))
        result = PrefillResult(application_id=app.id, state=app.status)

        terminal, reflection, _steps = service._run_plan_ops(app, state, plan, {}, result)

        assert reflection is None
        assert terminal is not None
        assert terminal.state == ApplicationState.BLOCKED_DETECTION
        assert len(spy.calls) == 1
        assert isinstance(spy.calls[0], Notification)


@pytest.mark.unit
class TestBlockedDetectionUsesCriticalUrgency:
    """#3: the cautious-pause hand-off must be CRITICAL, never deferred by
    quiet hours — it is exactly the "live-takeover / captcha hand-off" case
    the port's CRITICAL urgency is documented for."""

    def test_non_planner_blocked_detection_is_critical(self):
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        spy = _NotifySpy()
        service = _service(storage, spy)
        app = _app(cid).with_status(ApplicationState.SANDBOX_PROVISIONING).with_status(
            ApplicationState.PREFILLING
        )
        result = PrefillResult(application_id=app.id, state=app.status)
        event = DetectionEvent(
            id=DetectionEventId(new_id()),
            application_id=app.id,
            signal_type="captcha",
        )

        service._blocked_detection(app, result, event)

        assert spy.calls, "blocked-detection hand-off must emit a notification"
        assert spy.calls[0].urgency == NotificationUrgency.CRITICAL

    def test_planner_path_blocked_detection_is_critical(self):
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        spy = _NotifySpy()
        service = _service(storage, spy)
        app = _app(cid)
        state = PageState(url=f"{WORKDAY_URL}/apply", fields=())
        plan = Plan(ops=(StopOp(reason="captcha"),))
        result = PrefillResult(application_id=app.id, state=app.status)

        service._run_plan_ops(app, state, plan, {}, result)

        assert spy.calls, "planner-path detection block must emit a notification"
        assert spy.calls[0].urgency == NotificationUrgency.CRITICAL
