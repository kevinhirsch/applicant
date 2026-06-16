"""Scheduler — the 24/7 cadence that drives the engine (FR-DIG-1, FR-NOTIF-2, NFR-247-1).

Before this, nothing fired the per-unit work on a cadence: the agent loop never
ticked, the daily digest was never built on a schedule, and the notification
escalation ladder's ``advance`` was never called — so the Discord-hold -> email
escalation could not fire live. The scheduler closes that gap.

One ``tick(now)`` (pure, injected clock — no real sleeps):

1. **Ticks each active campaign's run loop** (``AgentLoop.tick``) so discovery /
   scoring / digest / pre-fill advance one step.
2. **Builds + delivers the daily digest** once per campaign per UTC day (FR-DIG-1):
   the per-campaign agent tick already delivers within the day, so the scheduler
   guards a single dedicated daily delivery keyed by ``(campaign, date)``.
3. **Advances the notification escalation ladder** (``NotificationService.advance``)
   so held Discord pushes escalate to email after the configured timeout (FR-NOTIF-2).

Behind the durable-orchestration port: on the shim an asyncio background task in
``app/lifespan.py`` calls ``tick`` on the configured interval (only when
``SCHEDULER_ENABLED``); on DBOS the real ``@scheduled`` workflow drives it. ``tick``
is unit-tested directly with an injected clock.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from applicant.observability.logging import get_logger

log = get_logger(__name__)


class Scheduler:
    def __init__(
        self,
        *,
        storage,
        agent_loop,
        digest_service=None,
        notification_service=None,
        final_approval_service=None,
    ) -> None:
        self._storage = storage
        self._loop = agent_loop
        self._digest = digest_service
        self._notifications = notification_service
        self._final_approval = final_approval_service
        # (campaign_id, UTC date) -> True once the dedicated daily digest was sent.
        self._daily_sent: dict[tuple[str, date], bool] = {}

    def tick(self, now: datetime | None = None) -> dict:
        """Advance every active campaign + daily digest + the escalation ladder."""
        now = now or datetime.now(UTC)
        ticked: list[str] = []
        digests_delivered: list[str] = []

        for campaign in self._active_campaigns():
            # (a) advance the per-campaign run loop one step.
            try:
                self._loop.tick(campaign.id, now)
                ticked.append(str(campaign.id))
            except Exception as exc:  # pragma: no cover - defensive
                log.warning("campaign_tick_failed", campaign_id=str(campaign.id), error=str(exc))
            # (b) ensure the DAILY digest is delivered once per UTC day (FR-DIG-1).
            if self._deliver_daily_digest(campaign.id, now):
                digests_delivered.append(str(campaign.id))

        # (c) advance the notification escalation ladder (FR-NOTIF-2).
        fired = self._advance_ladders(now)

        log.info(
            "scheduler_tick",
            campaigns=len(ticked),
            daily_digests=len(digests_delivered),
            ladder_fired=len(fired),
        )
        return {
            "ticked": ticked,
            "daily_digests": digests_delivered,
            "ladder_fired": fired,
        }

    # --- daily digest guard (FR-DIG-1) ------------------------------------
    def _deliver_daily_digest(self, campaign_id, now: datetime) -> bool:
        if self._digest is None:
            return False
        key = (str(campaign_id), now.date())
        if self._daily_sent.get(key):
            return False
        try:
            self._digest.deliver(campaign_id)
            self._daily_sent[key] = True
            return True
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("daily_digest_failed", campaign_id=str(campaign_id), error=str(exc))
            return False

    # --- escalation ladder (FR-NOTIF-2) -----------------------------------
    def _advance_ladders(self, now: datetime) -> list[str]:
        fired: list[str] = []
        if self._notifications is not None:
            fired.extend(self._notifications.advance(now))
        # FinalApprovalService.escalate delegates to the same notifier, so calling
        # both would double-advance; only call it when it is a distinct notifier.
        if (
            self._final_approval is not None
            and self._notifications is None
        ):
            fired.extend(self._final_approval.escalate(now))
        return fired

    def _active_campaigns(self):
        return [c for c in self._storage.campaigns.list() if getattr(c, "active", True)]
