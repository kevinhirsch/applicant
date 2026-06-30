"""Notification port (FR-NOTIF-1/2/3/5).

Channels: Discord (primary, one-click), web UI / in-app, email via Apprise;
extensible and configured in the setup wizard. The adapter implements the
escalation ladder (hold Discord 30s; in-app if the user is verifiably present;
email after the configurable timeout) and idempotency (acting on one channel
expires the others). The ladder is driven by an injected clock so the time-based
hops are deterministic in tests (no real sleeps).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable


class NotificationUrgency(str, Enum):
    NORMAL = "normal"  # digests/approvals; may respect quiet hours
    IMMEDIATE = "immediate"  # errors surface any hour (FR-NOTIF-5)
    # A targeted action that MUST reach the user even during quiet hours — e.g. a
    # live-takeover / captcha hand-off where the agent is blocked waiting on the
    # human. Unlike IMMEDIATE (a generic error fan-out), CRITICAL is a decision the
    # user acts on: it escalates like a NORMAL approval (in-app + Discord/email/push,
    # honoring web pre-emption) but is NEVER deferred by quiet hours (FR-NOTIF-5).
    CRITICAL = "critical"


class NotificationChannel(str, Enum):
    """The notification channels Apprise can dispatch to (FR-NOTIF-1)."""

    DISCORD = "discord"
    IN_APP = "in_app"
    EMAIL = "email"
    NTFY = "ntfy"  # push notifications via ntfy server (opt-in, urgent action alerts)
    PUSH = "ntfy"  # alias: PUSH is the logical name; ntfy is the transport


@dataclass(frozen=True)
class Notification:
    title: str
    body: str
    urgency: NotificationUrgency = NotificationUrgency.NORMAL
    deep_link: str | None = None  # e.g. redline surface or VNC link
    dedup_key: str | None = None  # idempotency across channels (FR-NOTIF-3)
    # Web-portal pre-emption (FR-NOTIF-2): a decision that can be approved on the
    # web portal first holds the Discord push for ``hold_seconds`` and never fires
    # Discord if the user acts (or is verifiably present) before the hold lapses.
    web_preemptable: bool = False


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
