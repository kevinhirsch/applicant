"""Notification port (FR-NOTIF-1/2/3/5).

Channels: Discord (primary, one-click), web UI, email via Apprise; extensible and
configured in the setup wizard. The adapter implements the escalation ladder
(hold Discord 30s; in-app if present; email after the configurable timeout) and
idempotency (acting on one channel expires the others).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable


class NotificationUrgency(str, Enum):
    NORMAL = "normal"  # digests/approvals; may respect quiet hours
    IMMEDIATE = "immediate"  # errors surface any hour (FR-NOTIF-5)


@dataclass(frozen=True)
class Notification:
    title: str
    body: str
    urgency: NotificationUrgency = NotificationUrgency.NORMAL
    deep_link: str | None = None  # e.g. redline surface or VNC link
    dedup_key: str | None = None  # idempotency across channels (FR-NOTIF-3)


@runtime_checkable
class NotificationPort(Protocol):
    """Outbound port for multi-channel notifications."""

    def notify(self, notification: Notification) -> str:
        """Dispatch a notification across configured channels; return a handle.

        Honors the escalation ladder and idempotency (FR-NOTIF-2/3).
        """
        ...

    def expire(self, dedup_key: str) -> None:
        """No-op/expire pending deliveries for ``dedup_key`` (acted elsewhere)."""
        ...

    def is_configured(self) -> bool:
        """True once at least one channel is configured (gates digests, FR-OOBE-3)."""
        ...
