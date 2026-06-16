"""Apprise + Discord notification adapter (FR-NOTIF-1/2/3/5).

# STAGE B — owned by Phase 1; flesh out here.

Channels: Discord (primary, one-click), web UI, email via Apprise. Phase 1 adds
the escalation ladder (30s Discord hold; in-app if present; email after timeout)
and cross-channel idempotency. The stub records dispatched notifications in memory
(so contract tests can assert idempotency/expiry semantics) and reports
configured/unconfigured for the channel gate (FR-OOBE-3).
"""

from __future__ import annotations

from applicant.ports.driven.notification import Notification


class AppriseNotifier:
    """NotificationPort adapter (in-memory stub until Phase 1)."""

    def __init__(self, *, discord_webhook_url: str = "", apprise_urls: str = "") -> None:
        self._discord = discord_webhook_url
        self._apprise = apprise_urls
        # dedup_key -> active handle (None once expired)
        self._sent: dict[str, str] = {}
        self._counter = 0

    def notify(self, notification: Notification) -> str:
        # STAGE B: real Apprise/Discord dispatch + escalation ladder (FR-NOTIF-2).
        self._counter += 1
        handle = f"notif-{self._counter}"
        key = notification.dedup_key or handle
        self._sent[key] = handle
        return handle

    def expire(self, dedup_key: str) -> None:
        # Idempotency: acting on one channel expires the others (FR-NOTIF-3).
        self._sent.pop(dedup_key, None)

    def is_active(self, dedup_key: str) -> bool:
        """Test/contract helper: is a notification still pending for this key?"""
        return dedup_key in self._sent

    def is_configured(self) -> bool:
        return bool(self._discord or self._apprise)
