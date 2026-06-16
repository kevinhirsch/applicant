"""Notification contract against the AppriseNotifier adapter."""

from __future__ import annotations

import pytest

from applicant.adapters.notification.apprise_notifier import AppriseNotifier
from tests.contract.base import NotificationPortContract


@pytest.mark.contract
class TestAppriseNotifierContract(NotificationPortContract):
    @pytest.fixture
    def adapter(self):
        return AppriseNotifier(discord_webhook_url="https://discord.test/wh")
