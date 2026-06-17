"""Real Apprise dispatch surfaces failures + builds URLs/body correctly (FR-NOTIF-1).

Hermetic: a spy stands in for the ``apprise`` module (monkeypatched into
``sys.modules``) so no network and no real Apprise dependency is exercised.
"""

from __future__ import annotations

import sys
import types

import pytest

from applicant.adapters.notification.apprise_notifier import (
    AppriseNotifier,
    NotificationDeliveryError,
)
from applicant.ports.driven.notification import Notification, NotificationUrgency


class _SpyApprise:
    def __init__(self, *, succeed: bool = True) -> None:
        self.added: list[str] = []
        self.notified: list[dict] = []
        self._succeed = succeed

    def add(self, url):
        self.added.append(url)
        return True

    def notify(self, *, title, body):
        self.notified.append({"title": title, "body": body})
        return self._succeed


def _install_spy(monkeypatch, spy):
    module = types.ModuleType("apprise")
    module.Apprise = lambda: spy
    monkeypatch.setitem(sys.modules, "apprise", module)


def test_failed_delivery_is_surfaced(monkeypatch):
    spy = _SpyApprise(succeed=False)
    _install_spy(monkeypatch, spy)
    notifier = AppriseNotifier(discord_webhook_url="discord://x/y", send_real=True)
    note = Notification(title="t", body="b", urgency=NotificationUrgency.IMMEDIATE)
    with pytest.raises(NotificationDeliveryError):
        notifier._send_real_dispatch("discord", note)


def test_discord_url_added_and_deeplink_body(monkeypatch):
    spy = _SpyApprise(succeed=True)
    _install_spy(monkeypatch, spy)
    notifier = AppriseNotifier(discord_webhook_url="discord://abc/def", send_real=True)
    note = Notification(
        title="Approval",
        body="Please review",
        deep_link="https://app.test/a/1",
        urgency=NotificationUrgency.NORMAL,
    )
    notifier._send_real_dispatch("discord", note)
    assert spy.added == ["discord://abc/def"]
    assert spy.notified[0]["body"] == "Please review\nhttps://app.test/a/1"


def test_email_urls_comma_split(monkeypatch):
    spy = _SpyApprise(succeed=True)
    _install_spy(monkeypatch, spy)
    notifier = AppriseNotifier(
        apprise_urls="mailto://a@x.test, mailto://b@x.test ,",
        send_real=True,
    )
    note = Notification(title="Digest", body="body", urgency=NotificationUrgency.NORMAL)
    notifier._send_real_dispatch("email", note)
    assert spy.added == ["mailto://a@x.test", "mailto://b@x.test"]
