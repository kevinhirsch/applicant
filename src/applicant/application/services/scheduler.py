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

import threading
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
        tick_services_factory=None,
        setup_service=None,
        interval_seconds: float | None = None,
    ) -> None:
        self._storage = storage
        self._loop = agent_loop
        self._digest = digest_service
        self._notifications = notification_service
        self._final_approval = final_approval_service
        # The cadence the live loop ticks at (``app/lifespan.py``), surfaced so the
        # status endpoint can report a ``next_tick`` estimate (FR-AGENT-7/FR-OBS-2).
        # None when unknown (in-memory / unit-driven schedulers).
        self._interval_seconds = interval_seconds
        # Live observability (FR-AGENT-7/FR-OBS-2): when the most recent tick ran and
        # whether one is executing right now. Set by ``tick``; read by ``state``. The
        # 24/7 loop owns the only writer, so a plain attribute is enough.
        self._last_tick_at: datetime | None = None
        self._tick_running: bool = False
        # FR-ONBOARD-2 / FR-OOBE-3: the automated-work gate. Each per-campaign loop tick
        # consults this and starts NO new work (discovery/digest/pipeline) while the
        # gate is closed — only in-flight recovery re-drive proceeds. The scheduler
        # holds the gate too so a tick is a fast no-op for new work before onboarding +
        # channels + LLM are satisfied; the escalation ladder still advances (it only
        # escalates already-emitted notifications, not new work).
        self._setup = setup_service
        # CONC-2: when set, called ONCE per tick to build a fresh, isolated
        # storage/session + storage-bound services so the 24/7 scheduler thread never
        # shares the request-scoped (non-thread-safe) SQLAlchemy Session. Returns a
        # dict with at least ``storage``/``agent_loop`` and an optional ``_session`` to
        # close after the tick. When None (in-memory / no DB), the shared singletons are
        # used (no Session to isolate).
        self._tick_services_factory = tick_services_factory
        # (campaign_id, UTC date) -> True. Retained for compatibility / introspection;
        # the loop now owns digest delivery (IDEM-1). CONC-3 prunes stale days.
        self._daily_sent: dict[tuple[str, date], bool] = {}
        # The per-day dedup pruning guard (CONC-3) drains old days.
        self._last_pruned_date: date | None = None
        # CONC: now that the tick runs OFF the event loop (in a worker thread), two
        # overlapping ticks could race the SAME campaign's ``loop.tick``. Guard each
        # campaign with a non-reentrant lock and SKIP a campaign whose prior tick is
        # still running rather than block (a slow campaign must not stall the others or
        # let the next interval pile a second tick onto it). The registry of locks is
        # itself guarded so two threads creating the same campaign's lock can't race.
        self._campaign_locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def tick(self, now: datetime | None = None) -> dict:
        """Advance every active campaign + daily digest + the escalation ladder.

        CONC-2: storage-bound work runs against a per-tick session when a factory is
        configured; the ladder advance (no storage) always uses the shared notifier.
        """
        now = now or datetime.now(UTC)
        self._tick_running = True
        self._last_tick_at = now
        # CONC-3: prune stale per-day dedup entries so the maps don't grow unbounded
        # over 24/7 operation.
        self._prune_daily_sent(now)

        services = self._tick_services_factory() if self._tick_services_factory else None
        loop = services["agent_loop"] if services else self._loop
        storage = services["storage"] if services else self._storage
        session = services.get("_session") if services else None

        ticked: list[str] = []
        try:
            for campaign in self._active_campaigns(storage):
                # (a) advance the per-campaign run loop one step. IDEM-1: the loop
                # itself delivers the daily digest at most once per (campaign, UTC day)
                # via its own ``_digest_sent`` guard, so the scheduler no longer
                # ALSO delivers it (that double-delivered the digest email + ready ping).
                # CONC: take the per-campaign lock without blocking — if a prior tick
                # for this campaign is still running, skip it this interval.
                lock = self._campaign_lock(campaign.id)
                if not lock.acquire(blocking=False):
                    log.info("campaign_tick_skipped_in_progress", campaign_id=str(campaign.id))
                    continue
                try:
                    loop.tick(campaign.id, now)
                    ticked.append(str(campaign.id))
                except Exception as exc:  # pragma: no cover - defensive
                    log.warning(
                        "campaign_tick_failed", campaign_id=str(campaign.id), error=str(exc)
                    )
                finally:
                    lock.release()
        finally:
            self._tick_running = False
            if session is not None:
                try:
                    session.close()
                except Exception:  # pragma: no cover - defensive
                    pass

        # (c) advance the notification escalation ladder (FR-NOTIF-2). The ladder is
        # in the (shared) notifier, not the DB, so it uses the shared service.
        fired = self._advance_ladders(now)

        log.info(
            "scheduler_tick",
            campaigns=len(ticked),
            ladder_fired=len(fired),
        )
        return {
            "ticked": ticked,
            # Retained for compatibility: digest delivery now happens inside the loop
            # tick (IDEM-1), so the scheduler reports none of its own.
            "daily_digests": [],
            "ladder_fired": fired,
        }

    def state(self, now: datetime | None = None) -> dict:
        """Live scheduler heartbeat for the status endpoint (FR-AGENT-7/FR-OBS-2).

        ``running`` is true while a tick executes; ``last_tick`` is when the most
        recent tick started; ``next_tick`` is the estimated next fire (``last_tick``
        + the configured interval) when the cadence is known. All timestamps ISO-8601.
        """
        now = now or datetime.now(UTC)
        last = self._last_tick_at
        nxt = None
        if last is not None and self._interval_seconds:
            from datetime import timedelta

            nxt = last + timedelta(seconds=float(self._interval_seconds))
        return {
            "running": bool(self._tick_running),
            "last_tick": last.isoformat() if last else None,
            "next_tick": nxt.isoformat() if nxt else None,
            "interval_seconds": self._interval_seconds,
            "now": now.isoformat(),
        }

    def run_now(self, campaign_id, now: datetime | None = None) -> dict:
        """Run a single tick for one campaign on demand (the operator 'Run now').

        Reuses the per-campaign lock so a manual run never races a scheduled tick: if
        a tick for this campaign is already in flight, this returns ``ran=False`` with
        a reason rather than piling a second concurrent tick onto it. Builds a fresh
        per-tick storage/session via the factory (CONC-2) just like the scheduled
        path, so it never touches the request-scoped Session.
        """
        import dataclasses

        now = now or datetime.now(UTC)
        services = self._tick_services_factory() if self._tick_services_factory else None
        loop = services["agent_loop"] if services else self._loop
        session = services.get("_session") if services else None

        lock = self._campaign_lock(campaign_id)
        if not lock.acquire(blocking=False):
            return {
                "campaign_id": str(campaign_id),
                "ran": False,
                "reason": "a run is already in progress for this campaign",
            }
        self._tick_running = True
        self._last_tick_at = now
        try:
            # force=True: a manual Run-now runs one pass even if the schedule is
            # paused / the run-mode auto-stop is met (the operator explicitly asked).
            try:
                result = loop.tick(campaign_id, now, force=True)
            except TypeError:
                # Tolerate loop stubs/older signatures without a ``force`` kwarg.
                result = loop.tick(campaign_id, now)
            if dataclasses.is_dataclass(result):
                payload = dataclasses.asdict(result)
            elif isinstance(result, dict):
                payload = dict(result)
            else:
                payload = {"ran": True}
            payload.setdefault("campaign_id", str(campaign_id))
            return payload
        finally:
            self._tick_running = False
            lock.release()
            if session is not None:
                try:
                    session.close()
                except Exception:  # pragma: no cover - defensive
                    pass

    def _campaign_lock(self, campaign_id) -> threading.Lock:
        """Return the per-campaign non-reentrant lock, creating it once (CONC)."""
        key = str(campaign_id)
        with self._locks_guard:
            lock = self._campaign_locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._campaign_locks[key] = lock
            return lock

    def _automated_work_allowed(self) -> bool:
        """True when automated work may begin (FR-ONBOARD-2/FR-OOBE-3).

        Treated as open when no ``setup_service`` is wired (legacy/unit tests).
        """
        if self._setup is None:
            return True
        try:
            return bool(self._setup.is_automated_work_allowed())
        except Exception:  # pragma: no cover - defensive: gate failure closes the gate
            return False

    def _prune_daily_sent(self, now: datetime) -> None:
        """CONC-3: drop daily-digest dedup entries from days other than today."""
        today = now.date()
        if self._last_pruned_date == today:
            return
        self._daily_sent = {
            key: v for key, v in self._daily_sent.items() if key[1] == today
        }
        self._last_pruned_date = today

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

    def _active_campaigns(self, storage=None):
        store = storage or self._storage
        return [c for c in store.campaigns.list() if getattr(c, "active", True)]
