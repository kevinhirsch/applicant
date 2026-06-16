"""Apprise + Discord notification adapter (FR-NOTIF-1/2/3/5).

# STAGE B — owned by Phase 1.

Channels: Discord (primary, one-click), email via Apprise, plus an in-app web sink.
Phase 1 deepens this with:

- an **escalation ladder** (FR-NOTIF-2): hold on Discord first; after a configurable
  timeout escalate to email — recorded here as ladder *steps* on each notification so
  the durable layer (Phase 2) can drive the actual time-based hops;
- **cross-channel idempotency** (FR-NOTIF-3): acting on one channel expires the others;
- **urgency / quiet-hours** posture (FR-NOTIF-5): IMMEDIATE notifications bypass quiet
  hours; NORMAL ones are flagged deferrable.

Network dispatch (real Apprise/Discord) is stubbed and offline-safe: deliveries are
recorded in memory so contract/unit tests can assert ladder + idempotency semantics
without sending anything. A real send is a single ``_dispatch`` swap later.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from applicant.ports.driven.notification import Notification, NotificationUrgency

# Escalation ladder (FR-NOTIF-2): ordered channels with a hold before the next hop.
_DISCORD_HOLD_SECONDS = 30


@dataclass
class _Delivery:
    handle: str
    notification: Notification
    ladder: list[str]
    sent_channels: list[str] = field(default_factory=list)
    active: bool = True


class AppriseNotifier:
    """NotificationPort adapter (offline-safe in-memory stub with real semantics)."""

    def __init__(
        self,
        *,
        discord_webhook_url: str = "",
        apprise_urls: str = "",
        in_app: bool = True,
        escalation_hold_seconds: int = _DISCORD_HOLD_SECONDS,
    ) -> None:
        self._discord = discord_webhook_url
        self._apprise = apprise_urls  # email/other Apprise URLs (comma-separated)
        self._in_app = in_app
        self._hold_seconds = escalation_hold_seconds
        # dedup_key -> active delivery (popped/deactivated on expiry)
        self._sent: dict[str, _Delivery] = {}
        self._counter = 0

    # --- channel configuration / gate (FR-OOBE-3) -------------------------
    def configured_channels(self) -> list[str]:
        channels: list[str] = []
        if self._discord:
            channels.append("discord")
        if self._apprise:
            channels.append("email")
        if self._in_app:
            channels.append("in_app")
        return channels

    def escalation_ladder(self, urgency: NotificationUrgency) -> list[str]:
        """Ordered channels to try (FR-NOTIF-2). IMMEDIATE fans out wider/faster."""
        ladder: list[str] = []
        if self._discord:
            ladder.append("discord")
        if self._in_app:
            ladder.append("in_app")
        if self._apprise:
            ladder.append("email")
        if not ladder:
            ladder = ["in_app"]  # always have a sink
        return ladder

    # --- dispatch ---------------------------------------------------------
    def _dispatch(self, channel: str, notification: Notification) -> None:
        # STAGE B: real Apprise/Discord send goes here; offline no-op for now.
        return None

    def notify(self, notification: Notification) -> str:
        self._counter += 1
        handle = f"notif-{self._counter}"
        ladder = self.escalation_ladder(notification.urgency)

        # First rung fires immediately; remaining rungs are escalation placeholders
        # the durable scheduler hops to after the hold (FR-NOTIF-2). IMMEDIATE
        # urgency fans out to every channel at once (FR-NOTIF-5).
        if notification.urgency is NotificationUrgency.IMMEDIATE:
            to_send = ladder
        else:
            to_send = ladder[:1]

        delivery = _Delivery(handle=handle, notification=notification, ladder=ladder)
        for channel in to_send:
            self._dispatch(channel, notification)
            delivery.sent_channels.append(channel)

        key = notification.dedup_key or handle
        self._sent[key] = delivery
        return handle

    def expire(self, dedup_key: str) -> None:
        """Idempotency: acting on one channel expires the others (FR-NOTIF-3)."""
        delivery = self._sent.pop(dedup_key, None)
        if delivery is not None:
            delivery.active = False

    # --- test/contract helpers -------------------------------------------
    def is_active(self, dedup_key: str) -> bool:
        """Is a notification still pending (not yet acted on) for this key?"""
        return dedup_key in self._sent

    def sent_channels(self, dedup_key: str) -> list[str]:
        """Channels a delivery has already fired on (introspection for tests)."""
        delivery = self._sent.get(dedup_key)
        return list(delivery.sent_channels) if delivery else []

    def pending_escalations(self, dedup_key: str) -> list[str]:
        """Ladder rungs not yet fired (the durable layer will hop to these)."""
        delivery = self._sent.get(dedup_key)
        if not delivery:
            return []
        return [c for c in delivery.ladder if c not in delivery.sent_channels]

    def is_configured(self) -> bool:
        return bool(self._discord or self._apprise or self._in_app)
