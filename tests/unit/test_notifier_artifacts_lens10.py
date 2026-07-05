"""Regression tests for audit lens 10 findings #14 and #15 (notification artifacts).

#14 — the Settings "Send a test" ping (``/channels/test``) uses IMMEDIATE urgency
purely to bypass quiet hours and fan out to every channel; ``_classify`` mapped
IMMEDIATE -> ``error`` unconditionally, so a user's very first in-app notification
rendered with the Portal's danger accent and "Heads up" tag. A real IMMEDIATE
alert (no ``channels-test`` dedup key) must still classify as ``error``.

#15 — the ntfy adapter added bare ``ntfy://`` URLs to Apprise with no ``priority=``
param, so an IMMEDIATE "agent is stuck" push and a routine NORMAL ping arrived at
the same default priority on the phone. NORMAL should keep ntfy's own default;
IMMEDIATE/CRITICAL should request ``priority=urgent``.

Hermetic: a spy stands in for the ``apprise`` module (monkeypatched into
``sys.modules``, mirroring ``test_apprise_real_dispatch.py``) so no network and no
real Apprise dependency is exercised.
"""

from __future__ import annotations

import sys
import types

from applicant.adapters.notification.apprise_notifier import (
    AppriseNotifier,
    _ntfy_url_with_priority,
)
from applicant.ports.driven.notification import Notification, NotificationUrgency


class _SpyApprise:
    def __init__(self) -> None:
        self.added: list[str] = []

    def add(self, url):
        self.added.append(url)
        return True

    def notify(self, *, title, body):
        return True


def _install_spy(monkeypatch, spy):
    module = types.ModuleType("apprise")
    module.Apprise = lambda: spy
    monkeypatch.setitem(sys.modules, "apprise", module)


# --- #14: channels-test classification --------------------------------------


def test_channels_test_classifies_as_info_not_error():
    notifier = AppriseNotifier(in_app=True)
    note = Notification(
        title="Applicant test notification",
        body="Channels are configured and working.",
        urgency=NotificationUrgency.IMMEDIATE,
        dedup_key="channels-test",
    )
    assert notifier._classify(note) == "info"


def test_real_immediate_alert_still_classifies_as_error():
    notifier = AppriseNotifier(in_app=True)
    note = Notification(
        title="Scheduler stalled",
        body="The scheduler has not ticked in 10 minutes.",
        urgency=NotificationUrgency.IMMEDIATE,
        dedup_key="scheduler-stall",
    )
    assert notifier._classify(note) == "error"


def test_channels_test_end_to_end_inbox_kind_is_info():
    """The full notify() path (not just _classify) lands the test ping as info."""
    notifier = AppriseNotifier(in_app=True)
    notifier.notify(
        Notification(
            title="Applicant test notification",
            body="Channels are configured and working.",
            urgency=NotificationUrgency.IMMEDIATE,
            dedup_key="channels-test",
        )
    )
    inbox = notifier.list_inbox()
    assert len(inbox) == 1
    assert inbox[0].kind == "info"


# --- #15: ntfy priority mapping -----------------------------------------------


def test_ntfy_url_priority_normal_is_default():
    note = Notification(title="t", body="b", urgency=NotificationUrgency.NORMAL)
    assert _ntfy_url_with_priority("ntfy://ntfy.sh/topic", note) == (
        "ntfy://ntfy.sh/topic?priority=default"
    )


def test_ntfy_url_priority_immediate_is_urgent():
    note = Notification(title="t", body="b", urgency=NotificationUrgency.IMMEDIATE)
    assert _ntfy_url_with_priority("ntfy://ntfy.sh/topic", note) == (
        "ntfy://ntfy.sh/topic?priority=urgent"
    )


def test_ntfy_url_priority_critical_is_urgent():
    note = Notification(title="t", body="b", urgency=NotificationUrgency.CRITICAL)
    assert _ntfy_url_with_priority("ntfy://ntfy.sh/topic", note) == (
        "ntfy://ntfy.sh/topic?priority=urgent"
    )


def test_ntfy_url_priority_appends_with_ampersand_when_query_present():
    note = Notification(title="t", body="b", urgency=NotificationUrgency.IMMEDIATE)
    assert _ntfy_url_with_priority("ntfy://ntfy.sh/topic?format=markdown", note) == (
        "ntfy://ntfy.sh/topic?format=markdown&priority=urgent"
    )


def test_ntfy_url_priority_leaves_explicit_override_alone():
    note = Notification(title="t", body="b", urgency=NotificationUrgency.IMMEDIATE)
    assert _ntfy_url_with_priority("ntfy://ntfy.sh/topic?priority=low", note) == (
        "ntfy://ntfy.sh/topic?priority=low"
    )


def test_send_real_dispatch_ntfy_carries_urgent_priority(monkeypatch):
    spy = _SpyApprise()
    _install_spy(monkeypatch, spy)
    notifier = AppriseNotifier(ntfy_url="ntfy://ntfy.sh/topic", send_real=True)
    note = Notification(
        title="Agent is stuck",
        body="Blocked on a CAPTCHA and needs you.",
        urgency=NotificationUrgency.CRITICAL,
    )
    notifier._send_real_dispatch("ntfy", note)
    assert spy.added == ["ntfy://ntfy.sh/topic?priority=urgent"]


def test_send_real_dispatch_ntfy_carries_default_priority_for_normal(monkeypatch):
    spy = _SpyApprise()
    _install_spy(monkeypatch, spy)
    notifier = AppriseNotifier(ntfy_url="ntfy://ntfy.sh/topic", send_real=True)
    note = Notification(
        title="Daily digest ready",
        body="Your matches are ready to review.",
        urgency=NotificationUrgency.NORMAL,
    )
    notifier._send_real_dispatch("ntfy", note)
    assert spy.added == ["ntfy://ntfy.sh/topic?priority=default"]
