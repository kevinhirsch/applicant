"""NotificationService (FR-NOTIF-1/2/3/5).

Orchestrates the multi-channel escalation ladder for decisions awaiting the user:

- a **decision is created server-side** and a notification is queued through the
  ``NotificationPort`` (FR-NOTIF-2): the Discord push is held ~30s for a web-portal
  pre-empt; the in-app surface is preferred when the user is verifiably present;
  email follows after the configurable timeout;
- **idempotency** (FR-NOTIF-3): ``acted`` expires every pending channel for the same
  decision so acting on one no-ops the others;
- **errors** are sent IMMEDIATE so they fan out any hour, bypassing quiet hours
  (FR-NOTIF-5).

Time is driven by the adapter's injected clock; ``advance`` steps the ladder
deterministically (no real sleeps), so the durable layer (Phase 2) can call it from
a scheduled tick and tests can step it directly.
"""

from __future__ import annotations

from datetime import datetime

from applicant.observability.logging import get_logger
from applicant.ports.driven.notification import Notification, NotificationUrgency

log = get_logger(__name__)


class NotificationService:
    def __init__(self, notification) -> None:
        self._notification = notification

    def dedup_key(self, decision_ref: str) -> str:
        """Stable cross-channel idempotency key for a decision (FR-NOTIF-3)."""
        return f"decision:{decision_ref}"

    # --- decision/approval ladder (FR-NOTIF-2) ----------------------------
    def notify_decision(
        self,
        decision_ref: str,
        *,
        title: str,
        body: str,
        deep_link: str | None = None,
    ) -> str:
        """Queue an approval notification that the web portal can pre-empt.

        Discord is held for the configured hold; in-app surfaces immediately;
        email escalates after the timeout (FR-NOTIF-2). Idempotent per decision.
        """
        return self._notification.notify(
            Notification(
                title=title,
                body=body,
                deep_link=deep_link,
                urgency=NotificationUrgency.NORMAL,
                dedup_key=self.dedup_key(decision_ref),
                web_preemptable=True,
            )
        )

    def acted(self, decision_ref: str) -> None:
        """The user acted on one channel — expire the others (FR-NOTIF-3)."""
        self._notification.expire(self.dedup_key(decision_ref))
        log.info("notification_acted", decision_ref=decision_ref)

    # --- errors (FR-NOTIF-5) ----------------------------------------------
    def notify_error(self, *, title: str, body: str, dedup_key: str | None = None) -> str:
        """Errors surface immediately, any hour, across every channel (FR-NOTIF-5)."""
        return self._notification.notify(
            Notification(
                title=title,
                body=body,
                urgency=NotificationUrgency.IMMEDIATE,
                dedup_key=dedup_key,
            )
        )

    # --- digest-ready ping (FR-DIG-2) -------------------------------------
    def notify_digest_ready(
        self, campaign_id: str, *, count: int, deep_link: str | None = None
    ) -> str:
        """Discord/in-app 'your digest is ready' ping (FR-DIG-2)."""
        body = (
            f"{count} viable role(s) await your review."
            if count
            else "No new viable roles today; tap to see what was searched and why."
        )
        return self._notification.notify(
            Notification(
                title="Daily digest ready",
                body=body,
                deep_link=deep_link or f"/digest?campaign={campaign_id}",
                urgency=NotificationUrgency.NORMAL,
                dedup_key=f"digest:{campaign_id}",
            )
        )

    # --- ladder advance (deterministic, FR-NOTIF-2) -----------------------
    def advance(self, now: datetime | None = None) -> list[str]:
        """Fire any escalation rungs now due. Returns channels fired this tick."""
        advance = getattr(self._notification, "advance", None)
        return advance(now) if advance else []
