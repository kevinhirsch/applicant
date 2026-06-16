"""Apprise + Discord notification adapter (FR-NOTIF-1/2/3/5).

# STAGE B — owned by Phase 1.

Channels: Discord (primary, one-click), email/SMTP via Apprise, plus an in-app web
sink. The adapter implements the full escalation ladder, idempotency, presence-aware
in-app surfacing, and the quiet-hours posture:

- **Escalation ladder** (FR-NOTIF-2): a web-pre-emptable decision holds the Discord
  push ~30s; if the user is verifiably present in the web UI (focused tab + recent
  input + open socket — modeled via an injected presence signal) the in-app channel
  is surfaced instead of Discord; if still undecided after a UI-configurable timeout
  (default 15 min) email is sent. The hops are driven by an **injected clock**, so
  ``advance(now)`` deterministically fires due rungs with no real sleeps.
- **Cross-channel idempotency** (FR-NOTIF-3): acting on one channel (``expire``)
  cancels every pending rung for that decision; later hops become no-ops.
- **Urgency / quiet hours** (FR-NOTIF-5): IMMEDIATE notifications (errors) fan out to
  every channel at once, any hour, bypassing quiet hours; NORMAL ones (approvals /
  digests) defer to the next allowed hour when quiet hours are configured (unless the
  campaign runs 24/7).

The real Apprise/Discord/SMTP send sits behind a single, clearly-marked boundary
(``_dispatch`` -> ``_send_real``). The DEFAULT lane records deliveries in memory (no
network) so contract/unit/BDD tests assert ladder + idempotency semantics offline;
``send_real=True`` (integration-gated) flips on the real Apprise send.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from applicant.observability.logging import get_logger
from applicant.ports.driven.notification import (
    Notification,
    NotificationChannel,
    NotificationUrgency,
)

log = get_logger(__name__)

# Escalation ladder defaults (FR-NOTIF-2).
_DISCORD_HOLD_SECONDS = 30
_EMAIL_TIMEOUT_SECONDS = 15 * 60  # 15 min, UI-configurable


@dataclass
class _Rung:
    """One escalation hop: a channel to fire ``due_at`` (epoch-relative seconds)."""

    channel: str
    due_at: float
    fired: bool = False


@dataclass
class _Delivery:
    handle: str
    notification: Notification
    rungs: list[_Rung] = field(default_factory=list)
    sent_channels: list[str] = field(default_factory=list)
    active: bool = True


@dataclass(frozen=True)
class CapturedSend:
    """An offline-captured dispatch (for tests / the in-app sink)."""

    channel: str
    title: str
    body: str
    deep_link: str | None
    urgency: str


def _default_clock() -> datetime:
    return datetime.now(UTC)


class AppriseNotifier:
    """NotificationPort adapter: real semantics, offline-safe by default."""

    def __init__(
        self,
        *,
        discord_webhook_url: str = "",
        apprise_urls: str = "",
        in_app: bool = True,
        escalation_hold_seconds: int = _DISCORD_HOLD_SECONDS,
        email_timeout_seconds: int = _EMAIL_TIMEOUT_SECONDS,
        clock: Callable[[], datetime] | None = None,
        presence: Callable[[], bool] | None = None,
        quiet_hours: tuple[int, int] | None = None,
        always_on: bool = False,
        send_real: bool = False,
    ) -> None:
        self._discord = discord_webhook_url
        self._apprise = apprise_urls  # email/SMTP/other Apprise URLs (comma-separated)
        self._in_app = in_app
        self._hold_seconds = escalation_hold_seconds
        self._email_timeout = email_timeout_seconds
        self._clock = clock or _default_clock
        # Presence signal (FR-NOTIF-2): True when the user is verifiably present in
        # the web UI (focused tab + recent input + open socket). Default: absent.
        self._presence = presence
        # Quiet hours (FR-NOTIF-5): (start_hour, end_hour) in local 24h; NORMAL
        # notifications defer into this window unless the campaign is 24/7.
        self._quiet_hours = quiet_hours
        self._always_on = always_on
        self._send_real = send_real
        # dedup_key -> active delivery (deactivated on expiry, FR-NOTIF-3)
        self._sent: dict[str, _Delivery] = {}
        self._counter = 0
        # In-app sink: notifications surfaced in the portal (FR-UI-3 feed).
        self._inbox: list[CapturedSend] = []
        # Offline capture of every fired dispatch (introspection for tests).
        self._captured: list[CapturedSend] = []

    # --- channel configuration / gate (FR-OOBE-3) -------------------------
    def configured_channels(self) -> list[str]:
        channels: list[str] = []
        if self._discord:
            channels.append(NotificationChannel.DISCORD.value)
        if self._in_app:
            channels.append(NotificationChannel.IN_APP.value)
        if self._apprise:
            channels.append(NotificationChannel.EMAIL.value)
        return channels

    def is_configured(self) -> bool:
        return bool(self._discord or self._apprise or self._in_app)

    def has_discord(self) -> bool:
        return bool(self._discord)

    def has_email(self) -> bool:
        return bool(self._apprise)

    def configure(
        self, *, discord_webhook_url: str | None = None, apprise_urls: str | None = None
    ) -> None:
        """Update channel config on the live adapter (wizard wiring, FR-OOBE-2).

        Lets the OOBE channels step reconfigure the running notifier without a
        restart (zero-CLI). Only provided channels are updated.
        """
        if discord_webhook_url is not None:
            self._discord = discord_webhook_url
        if apprise_urls is not None:
            self._apprise = apprise_urls

    # --- ladder construction (FR-NOTIF-2) ---------------------------------
    def _now_secs(self) -> float:
        return self._clock().timestamp()

    def _build_rungs(self, notification: Notification) -> list[_Rung]:
        """Plan the escalation hops for one notification (FR-NOTIF-2)."""
        now = self._now_secs()
        rungs: list[_Rung] = []

        if notification.urgency is NotificationUrgency.IMMEDIATE:
            # Errors fan out to every configured channel at once, any hour (FR-NOTIF-5).
            for ch in self.configured_channels():
                rungs.append(_Rung(channel=ch, due_at=now))
            if not rungs:
                rungs.append(_Rung(channel=NotificationChannel.IN_APP.value, due_at=now))
            return rungs

        # NORMAL: in-app is always available immediately as the home-base sink.
        if self._in_app:
            rungs.append(_Rung(channel=NotificationChannel.IN_APP.value, due_at=now))

        # Web-pre-emptable decisions hold the Discord push so a quick web approval
        # (or verifiable presence) can pre-empt it; otherwise Discord fires now.
        if self._discord:
            discord_delay = self._hold_seconds if notification.web_preemptable else 0
            rungs.append(
                _Rung(channel=NotificationChannel.DISCORD.value, due_at=now + discord_delay)
            )

        # Email is the final rung after the configurable timeout (FR-NOTIF-2).
        if self._apprise:
            rungs.append(
                _Rung(channel=NotificationChannel.EMAIL.value, due_at=now + self._email_timeout)
            )

        if not rungs:
            rungs.append(_Rung(channel=NotificationChannel.IN_APP.value, due_at=now))
        return rungs

    # --- quiet hours (FR-NOTIF-5) -----------------------------------------
    def _in_quiet_hours(self, when: datetime) -> bool:
        if self._always_on or not self._quiet_hours:
            return False
        start, end = self._quiet_hours
        hour = when.hour
        if start == end:
            return False
        if start < end:
            return start <= hour < end
        # Window wraps midnight (e.g. 22 -> 7).
        return hour >= start or hour < end

    # --- dispatch ---------------------------------------------------------
    def _dispatch(self, channel: str, notification: Notification) -> None:
        captured = CapturedSend(
            channel=channel,
            title=notification.title,
            body=notification.body,
            deep_link=notification.deep_link,
            urgency=notification.urgency.value,
        )
        self._captured.append(captured)
        if channel == NotificationChannel.IN_APP.value:
            self._inbox.append(captured)
        if self._send_real:
            self._send_real_dispatch(channel, notification)
        log.info(
            "notification_dispatched",
            channel=channel,
            urgency=notification.urgency.value,
            dedup_key=notification.dedup_key,
        )

    def _send_real_dispatch(self, channel: str, notification: Notification) -> None:
        """REAL network boundary (FR-NOTIF-1) — integration-gated only.

        Builds an Apprise client for the channel and sends. The in-app channel is
        local (no network); Discord + email go over the wire via Apprise URLs.
        """
        if channel == NotificationChannel.IN_APP.value:
            return  # local sink, no network
        import apprise  # imported lazily so the offline lane needs no Apprise import

        client = apprise.Apprise()
        if channel == NotificationChannel.DISCORD.value and self._discord:
            client.add(self._discord)
        elif channel == NotificationChannel.EMAIL.value and self._apprise:
            for url in (u.strip() for u in self._apprise.split(",") if u.strip()):
                client.add(url)
        body = notification.body
        if notification.deep_link:
            body = f"{body}\n{notification.deep_link}"
        client.notify(title=notification.title, body=body)

    # --- public API -------------------------------------------------------
    def notify(self, notification: Notification) -> str:
        self._counter += 1
        handle = f"notif-{self._counter}"
        rungs = self._build_rungs(notification)
        delivery = _Delivery(handle=handle, notification=notification, rungs=rungs)
        key = notification.dedup_key or handle
        self._sent[key] = delivery
        # Fire any rung already due (NORMAL in-app + Discord-now; IMMEDIATE all).
        self._fire_due(delivery, self._now_secs())
        return handle

    def advance(self, now: datetime | None = None) -> list[str]:
        """Fire any escalation rungs now due across active deliveries (FR-NOTIF-2).

        Driven by the injected clock so tests step time deterministically. Returns
        the list of channels fired on this tick.
        """
        ts = (now or self._clock()).timestamp()
        fired: list[str] = []
        for delivery in list(self._sent.values()):
            fired.extend(self._fire_due(delivery, ts))
        return fired

    def _fire_due(self, delivery: _Delivery, ts: float) -> list[str]:
        if not delivery.active:
            return []
        fired: list[str] = []
        when = datetime.fromtimestamp(ts, tz=UTC)
        for rung in delivery.rungs:
            if rung.fired or rung.due_at > ts:
                continue
            # Presence pre-emption (FR-NOTIF-2): when the user is verifiably present
            # in the web UI, suppress the Discord push in favor of the in-app surface.
            if (
                rung.channel == NotificationChannel.DISCORD.value
                and delivery.notification.web_preemptable
                and self._presence is not None
                and self._presence()
            ):
                rung.fired = True
                continue
            # Quiet hours (FR-NOTIF-5): defer NORMAL hops to the next allowed hour;
            # IMMEDIATE always fires. (Email/Discord deferral; in-app always surfaces.)
            if (
                delivery.notification.urgency is NotificationUrgency.NORMAL
                and rung.channel != NotificationChannel.IN_APP.value
                and self._in_quiet_hours(when)
            ):
                continue
            self._dispatch(rung.channel, delivery.notification)
            rung.fired = True
            delivery.sent_channels.append(rung.channel)
            fired.append(rung.channel)
        return fired

    def expire(self, dedup_key: str) -> None:
        """Idempotency: acting on one channel expires the others (FR-NOTIF-3)."""
        delivery = self._sent.get(dedup_key)
        if delivery is not None:
            delivery.active = False
            for rung in delivery.rungs:
                rung.fired = True  # cancel any not-yet-fired hops
            self._sent.pop(dedup_key, None)

    # --- in-app sink / presence (FR-UI-3 feed, FR-NOTIF-2) ----------------
    def inbox(self) -> list[CapturedSend]:
        """In-app notifications surfaced in the portal (drains nothing)."""
        return list(self._inbox)

    def set_presence(self, present: bool) -> None:
        """Override the presence signal (used when no provider is injected)."""
        self._presence = (lambda: present) if present else (lambda: False)

    # --- test/contract helpers -------------------------------------------
    def is_active(self, dedup_key: str) -> bool:
        return dedup_key in self._sent

    def sent_channels(self, dedup_key: str) -> list[str]:
        delivery = self._sent.get(dedup_key)
        return list(delivery.sent_channels) if delivery else []

    def pending_escalations(self, dedup_key: str) -> list[str]:
        """Ladder rungs not yet fired (the next hops the scheduler will fire)."""
        delivery = self._sent.get(dedup_key)
        if not delivery:
            return []
        return [r.channel for r in delivery.rungs if not r.fired]

    def captured(self) -> list[CapturedSend]:
        """Every offline-captured dispatch (introspection for tests)."""
        return list(self._captured)
