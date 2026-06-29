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
from applicant.observability.metrics import (
    DEFAULT_FAILURE_ALERT_THRESHOLD,
    Metrics,
    get_metrics,
)

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
        curation_service=None,
        curation_schedule: str = "off",
        run_summaries_provider=None,
        status_update_service=None,
        status_update_schedule: str = "off",
        essentials_nudge_service=None,
        essentials_nudge_schedule: str = "off",
        retention_service=None,
        retention_schedule: str = "off",
        metrics: Metrics | None = None,
        failure_alert_threshold: int = DEFAULT_FAILURE_ALERT_THRESHOLD,
    ) -> None:
        self._storage = storage
        self._loop = agent_loop
        self._digest = digest_service
        self._notifications = notification_service
        self._final_approval = final_approval_service
        # FR-MIND-7: the closed-loop curation nudge. ``curation_service`` is the
        # process-lived curator whose cross-tick dedupe lives in the injected ledger,
        # NOT on the instance (FR-MIND-10); the per-tick service from the factory is
        # preferred when present. ``curation_schedule`` gates the cadence: ``off``/
        # empty (default) disables it entirely, anything else opts in to a
        # once-per-UTC-day nudge keyed like the daily digest, so the substrate ships
        # dormant (FR-MIND-12) until configured. ``run_summaries_provider(storage,
        # now)`` supplies the recent run summaries to review; ``None`` => no summaries
        # (a fast no-op that still marks the day so re-ticks stay idempotent). The
        # nudge is gated on the automated-work gate exactly like new work.
        self._curation = curation_service
        self._curation_schedule = (curation_schedule or "off").strip().lower()
        self._run_summaries_provider = run_summaries_provider
        # (UTC date) -> True. A once-per-day guard so re-running a tick the same day
        # never re-runs the nudge. The proposal ledger is content-hashed too, so even
        # a double-run could not duplicate proposals (defense in depth, FR-MIND-7).
        self._curation_days: dict[date, bool] = {}
        # FR-AGENT-7 / FR-OBS-2: the proactive periodic agent status update — the PUSH
        # sibling of the chatbot self-report. ``status_update_service`` assembles a short,
        # first-person plain-language summary from read-only state and pushes it through
        # the EXISTING notification path (in-app inbox + opt-in fan-out, NOT a parallel
        # channel). ``status_update_schedule`` gates the cadence exactly like the curation
        # nudge: ``off``/empty (default) keeps it dormant — a fast no-op with NO behavior
        # change; anything else opts in to a once-per-UTC-day push keyed like the daily
        # digest. Gated on the automated-work gate, idempotent per (campaign, UTC day).
        self._status_update = status_update_service
        self._status_update_schedule = (status_update_schedule or "off").strip().lower()
        # (campaign_id, UTC date) -> True. Once-per-day guard so re-ticking the same day
        # never re-pushes the update (mirrors the digest/curation per-day idempotency).
        self._status_update_days: dict[tuple[str, date], bool] = {}
        # FR-NOTIF / FR-ONBOARD: the proactive "I'm still blocked on essentials" nudge.
        # ``essentials_nudge_service`` checks each active campaign's apply-readiness and,
        # when automated work is BLOCKED specifically because apply-essentials are missing,
        # pushes ONE friendly first-person notification naming exactly what's still needed
        # — through the EXISTING notification path (in-app inbox + opt-in fan-out, NOT a
        # parallel channel). ``essentials_nudge_schedule`` gates the cadence exactly like
        # the curation/status-update nudges: ``off``/empty (default) keeps it dormant — a
        # fast no-op with NO behavior change; anything else opts in to a once-per-UTC-day
        # push keyed per (campaign, UTC day). Unlike the other nudges this fires while the
        # automated-work gate is CLOSED (the whole point is the user hasn't unblocked it),
        # but ONLY when the close is due to missing apply-essentials — never otherwise.
        self._essentials_nudge = essentials_nudge_service
        self._essentials_nudge_schedule = (essentials_nudge_schedule or "off").strip().lower()
        # (campaign_id, UTC date) -> True. Once-per-day guard so re-ticking the same day
        # never re-pushes the nudge (mirrors the status-update per-day idempotency).
        self._essentials_nudge_days: dict[tuple[str, date], bool] = {}
        # #363: PII retention sweep. ``retention_service.prune_pii_older_than()`` removes
        # stored PII/EEO older than the configured window. ``retention_schedule`` gates
        # the cadence: ``off``/empty (default) disables it entirely; anything else opts
        # in to a once-per-UTC-day sweep so the substrate ships dormant until configured.
        self._retention = retention_service
        self._retention_schedule = (retention_schedule or "off").strip().lower()
        # (UTC date) -> True. Once-per-day guard so re-running a tick the same day never
        # re-runs the sweep (follows the same pattern as curation/status-update).
        self._retention_days: dict[date, bool] = {}
        # The cadence the live loop ticks at (``app/lifespan.py``), surfaced so the
        # status endpoint can report a ``next_tick`` estimate (FR-AGENT-7/FR-OBS-2).
        # None when unknown (in-memory / unit-driven schedulers).
        self._interval_seconds = interval_seconds
        # Live observability (FR-AGENT-7/FR-OBS-2): when the most recent tick ran and
        # whether one is executing right now. Set by ``tick``; read by ``state``. The
        # 24/7 loop owns the only writer, so a plain attribute is enough.
        self._last_tick_at: datetime | None = None
        self._tick_running: bool = False
        # FR-OBS-2 / NFR-OPS: the operational metrics surface (tick counts, success/
        # failure, scheduler-liveness heartbeat) that updates EVERY tick and the
        # consecutive-tick-failure alert ladder. Defaults to the process-lived
        # singleton (so the agent-status surface + a real exporter read the same
        # registry); tests inject a fresh isolated ``Metrics()`` to avoid global
        # bleed-through. The threshold is the configurable N consecutive failures that
        # raises ONE operator alert through the EXISTING notification ladder.
        self._metrics = metrics or get_metrics()
        self._metrics.set_failure_alert_threshold(failure_alert_threshold)
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
        # Prefer the per-tick curation service (shares the SAME process-lived ledger +
        # memory adapters as the main one, FR-MIND-10) so the nudge runs against the
        # isolated per-tick session/storage; fall back to the shared service otherwise.
        curation = (
            services.get("curation_service") if services else None
        ) or self._curation

        ticked: list[str] = []
        # FR-OBS-2 / NFR-OPS: track this tick's health so the metrics surface records
        # success/failure and the consecutive-failure alert can fire. A tick is a
        # FAILURE when (a) an unexpected exception escapes the tick body, or (b) there
        # were active campaigns but EVERY one of them failed its loop tick (a real
        # stall — not a single transient blip on one campaign).
        tick_ok = True
        campaign_attempts = 0
        campaign_failures = 0
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
                campaign_attempts += 1
                try:
                    loop.tick(campaign.id, now)
                    ticked.append(str(campaign.id))
                except Exception as exc:
                    campaign_failures += 1
                    log.warning(
                        "campaign_tick_failed", campaign_id=str(campaign.id), error=str(exc)
                    )
                finally:
                    lock.release()
            # (b) run the closed-loop curation nudge once per UTC day (FR-MIND-7),
            #     gated + idempotent, while the per-tick storage/session is still open
            #     (its summaries provider may read recent runs from it). Runs inside the
            #     same try so the session is always closed in the finally below.
            curated = self._run_curation(curation, storage, now)
            # (b2) push the proactive periodic agent status update once per UTC day
            #      (FR-AGENT-7/FR-OBS-2), gated + idempotent. Uses the SAME campaigns the
            #      loop ticked above so a freshly-removed campaign gets none.
            status_pushed = self._run_status_updates(storage, now)
            # (b3) push the proactive "still blocked on essentials" nudge once per
            #      (campaign, UTC day) (FR-NOTIF / FR-ONBOARD), gated + idempotent. Uses
            #      the SAME campaigns the loop ticked so a freshly-removed campaign gets none.
            essentials_nudged = self._run_essentials_nudges(storage, now)
            # (b4) #363: run the PII retention sweep once per UTC day, gated +
            #     idempotent. Prunes stored PII/EEO older than the configured window.
            retention_pruned = self._run_pii_retention(now)
        except Exception:
            # The tick body itself blew up (services factory / campaign query / a nudge
            # ran unguarded) — count it as a failed tick for stall detection, then
            # re-raise so the caller (lifespan / DBOS workflow) still sees the error.
            tick_ok = False
            self._record_tick_metrics(now, success=False, campaigns=len(ticked))
            raise
        finally:
            self._tick_running = False
            if session is not None:
                try:
                    session.close()
                except Exception:  # pragma: no cover - defensive
                    pass

        # A tick where every attempted campaign failed is a stall, not a success.
        if campaign_attempts > 0 and campaign_failures == campaign_attempts:
            tick_ok = False

        # (c) advance the notification escalation ladder (FR-NOTIF-2). The ladder is
        # in the (shared) notifier, not the DB, so it uses the shared service.
        fired = self._advance_ladders(now)

        # (d) FR-OBS-2 / NFR-OPS: record the tick on the metrics surface (heartbeat +
        # success/failure counters) and raise ONE operator alert through the existing
        # notification ladder if N consecutive ticks have now failed (idempotent).
        self._record_tick_metrics(
            now, success=tick_ok, campaigns=len(ticked), ladder_fired=len(fired)
        )

        log.info(
            "scheduler_tick",
            campaigns=len(ticked),
            ladder_fired=len(fired),
            tick_ok=tick_ok,
            curation_reviewed=curated.get("reviewed", 0),
            status_updates=len(status_pushed),
            essentials_nudges=len(essentials_nudged),
        )
        return {
            "ticked": ticked,
            # Retained for compatibility: digest delivery now happens inside the loop
            # tick (IDEM-1), so the scheduler reports none of its own.
            "daily_digests": [],
            "ladder_fired": fired,
            # FR-MIND-7 / FR-OBS-2: a small introspectable result for the curation
            # nudge — ``ran`` False (with a reason) when disabled / gated / already-run.
            "curation": curated,
            # FR-AGENT-7 / FR-OBS-2: campaign ids that got a status update pushed this
            # tick (empty when disabled / gated / already-pushed / nothing to report).
            "status_updates": status_pushed,
            # FR-NOTIF / FR-ONBOARD: campaign ids that got a "still blocked on essentials"
            # nudge pushed this tick (empty when disabled / already-pushed / gate open /
            # nothing missing / blocked for some other reason).
            "essentials_nudges": essentials_nudged,
            # #363: PII retention sweep — pruned count (0 when disabled/gated/already-run).
            "pii_retention": retention_pruned,
            # FR-OBS-2 / NFR-OPS: this tick's health (False when every attempted campaign
            # failed). The metrics surface tracks the cross-tick consecutive-failure run.
            "tick_ok": tick_ok,
        }

    # --- operational metrics + consecutive-failure alert (FR-OBS-2 / NFR-OPS) ---
    def _record_tick_metrics(
        self, now: datetime, *, success: bool, **counters: int
    ) -> None:
        """Record this tick on the metrics surface and alert on a sustained stall.

        Updates the tick counters + scheduler-liveness heartbeat for EVERY tick
        (FR-OBS-2), then asks the metrics surface whether N consecutive ticks have now
        failed. If so it raises ONE operator alert through the EXISTING notification
        ladder (``NotificationService.notify_error`` — IMMEDIATE urgency, surfaced any
        hour, FR-NOTIF-5) rather than only a log line. The alert is idempotent: the
        metrics surface latches after the first alert of a stall and re-arms only after
        a tick succeeds, so a long outage produces ONE alert, not one per tick.
        """
        try:
            self._metrics.record_tick(success=success, now=now, **counters)
            alert = self._metrics.consecutive_failure_alert()
        except Exception:  # pragma: no cover - defensive: metrics must never break a tick
            return
        if alert:
            self._raise_failure_alert(alert)

    def _raise_failure_alert(self, alert: dict) -> None:
        """Surface ONE operator alert for a sustained scheduler stall (FR-OBS-2)."""
        count = alert.get("consecutive_failures")
        threshold = alert.get("threshold")
        log.error(
            "scheduler_consecutive_failure_alert",
            consecutive_failures=count,
            threshold=threshold,
        )
        notifier = self._notifications
        if notifier is None:
            return
        try:
            notifier.notify_error(
                title="Your job-search agent is stuck",
                body=(
                    f"I've hit a problem on {count} runs in a row and have paused "
                    "automatic work until it clears. Please check on me when you can."
                ),
                # One dedup key per stall episode so even if this fired twice the
                # notifier collapses it to a single operator alert (defense in depth).
                dedup_key="scheduler_stall",
            )
        except Exception as exc:  # pragma: no cover - defensive: alert send is best-effort
            log.warning("scheduler_failure_alert_send_failed", error=str(exc))

    def metrics_snapshot(self) -> dict:
        """A read-only snapshot of the operational metrics surface (FR-OBS-2)."""
        try:
            return self._metrics.snapshot()
        except Exception:  # pragma: no cover - defensive
            return {}

    def state(self, now: datetime | None = None) -> dict:
        """Live scheduler heartbeat for the status endpoint (FR-AGENT-7/FR-OBS-2).

        ``running`` is true while a tick executes; ``last_tick`` is when the most
        recent tick started; ``next_tick`` is the estimated next fire (``last_tick``
        + the configured interval) when the cadence is known. ``metrics`` carries the
        operational counters + scheduler-liveness heartbeat (FR-OBS-2 / NFR-OPS) so the
        status surface exposes tick totals, success/failure, and whether a stall alert
        is currently armed. All timestamps ISO-8601.
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
            "metrics": self.metrics_snapshot(),
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
        # Show "working now" while the manual run executes, but DON'T overwrite
        # ``_last_tick_at``: that tracks the SCHEDULED cadence (it drives the
        # next-tick estimate), and a manual Run-now must not make the status chip
        # claim the scheduler just ticked / shift its next-run countdown.
        self._tick_running = True
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

    # --- closed-loop curation nudge (FR-MIND-7) ---------------------------
    def _run_curation(self, curation, storage, now: datetime) -> dict:
        """Run the curation nudge at most once per UTC day, gated + idempotent.

        Fast no-op when (a) disabled (``CURATION_SCHEDULE`` off / no service), (b) the
        automated-work gate is closed, or (c) the nudge already ran today. Otherwise it
        asks the (optional) summaries provider for recent runs and proposes
        memory/skill updates; the curator stages them for review (FR-MIND-9) and dedupes
        via its process-lived ledger (FR-MIND-10), so this is safe to re-enter and never
        duplicates proposals (FR-MIND-7). Memory/skills proposed are advisory only and
        confer no authority (FR-MIND-11).
        """
        if curation is None or self._curation_schedule in ("", "off"):
            return {"ran": False, "reason": "disabled"}
        if not self._automated_work_allowed():
            return {"ran": False, "reason": "gated"}
        today = now.date()
        self._prune_curation_days(today)
        if self._curation_days.get(today):
            return {"ran": False, "reason": "already_ran_today"}
        # Mark BEFORE running so a crash mid-nudge doesn't loop it the same day; the
        # content-hashed ledger keeps the actual proposals idempotent regardless.
        self._curation_days[today] = True
        summaries: tuple = ()
        if self._run_summaries_provider is not None:
            try:
                summaries = tuple(self._run_summaries_provider(storage, now) or ())
            except Exception as exc:  # pragma: no cover - defensive
                log.warning("curation_summaries_failed", error=str(exc))
                summaries = ()
        try:
            result = curation.run_curation_tick(summaries)
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("curation_nudge_failed", error=str(exc))
            return {"ran": False, "reason": "error"}
        return {
            "ran": True,
            "reviewed": int(getattr(result, "reviewed", 0)),
            "staged": int(getattr(result, "staged", 0)),
            "auto_applied": int(getattr(result, "auto_applied", 0)),
        }

    def _prune_curation_days(self, today: date) -> None:
        """Keep the once-per-day curation guard from growing over 24/7 operation."""
        if today in self._curation_days and len(self._curation_days) == 1:
            return
        self._curation_days = {
            d: v for d, v in self._curation_days.items() if d == today
        }

    # --- proactive periodic status update (FR-AGENT-7 / FR-OBS-2) ---------
    def _run_status_updates(self, storage, now: datetime) -> list[str]:
        """Push the periodic agent status update at most once per (campaign, UTC day).

        Fast no-op when (a) disabled (``STATUS_UPDATE_SCHEDULE`` off / no service), or
        (b) the automated-work gate is closed. For each active campaign that has not yet
        received today's update, asks the service to assemble + push it through the
        existing notification path; the service emits NOTHING when there is nothing
        truthful to report (FR-AGENT-5), in which case the day is still marked so a
        re-tick does not retry it. Returns the campaign ids actually pushed this tick.
        """
        if self._status_update is None or self._status_update_schedule in ("", "off"):
            return []
        if not self._automated_work_allowed():
            return []
        today = now.date()
        self._prune_status_update_days(today)
        pushed: list[str] = []
        for campaign in self._active_campaigns(storage):
            key = (str(campaign.id), today)
            if self._status_update_days.get(key):
                continue
            # Mark BEFORE emitting so a crash mid-push doesn't loop it the same day; the
            # notifier dedup key (per campaign + UTC day) is the second line of defense.
            self._status_update_days[key] = True
            try:
                handle = self._status_update.emit(campaign.id, now)
            except Exception as exc:  # pragma: no cover - defensive
                log.warning(
                    "status_update_failed", campaign_id=str(campaign.id), error=str(exc)
                )
                continue
            if handle:
                pushed.append(str(campaign.id))
        return pushed

    def _prune_status_update_days(self, today: date) -> None:
        """Keep the once-per-day status-update guard bounded over 24/7 operation."""
        self._status_update_days = {
            k: v for k, v in self._status_update_days.items() if k[1] == today
        }

    # --- proactive "still blocked on essentials" nudge (FR-NOTIF / FR-ONBOARD) ---
    def _run_essentials_nudges(self, storage, now: datetime) -> list[str]:
        """Push the "I'm still blocked" nudge at most once per (campaign, UTC day).

        Fast no-op when disabled (``ESSENTIALS_NUDGE_SCHEDULE`` off / no service). For
        each active campaign that hasn't been nudged today, asks the service to check
        apply-readiness and push ONE friendly first-person notification naming exactly
        the missing apply-essentials. The service emits NOTHING when the gate is open /
        nothing's missing (FR-AGENT-5: the list comes from ``apply_readiness``, never
        fabricated), in which case the day is still marked so a re-tick does not retry.

        Distinct from the curation/status-update nudges, this does NOT consult the
        automated-work gate: the gate is CLOSED precisely because essentials are missing
        (that is the situation it exists to nudge about). It is still scoped to that one
        cause — the service only emits when ``apply_readiness`` reports missing essentials,
        so a gate closed for any OTHER reason (no LLM, etc.) yields no nudge. Returns the
        campaign ids actually nudged this tick.
        """
        if self._essentials_nudge is None or self._essentials_nudge_schedule in ("", "off"):
            return []
        today = now.date()
        self._prune_essentials_nudge_days(today)
        pushed: list[str] = []
        for campaign in self._active_campaigns(storage):
            key = (str(campaign.id), today)
            if self._essentials_nudge_days.get(key):
                continue
            # Mark BEFORE emitting so a crash mid-push doesn't loop it the same day; the
            # notifier dedup key (per campaign + UTC day) is the second line of defense.
            self._essentials_nudge_days[key] = True
            try:
                handle = self._essentials_nudge.emit(campaign.id, now)
            except Exception as exc:  # pragma: no cover - defensive
                log.warning(
                    "essentials_nudge_failed", campaign_id=str(campaign.id), error=str(exc)
                )
                continue
            if handle:
                pushed.append(str(campaign.id))
        return pushed

    def _prune_essentials_nudge_days(self, today: date) -> None:
        """Keep the once-per-day essentials-nudge guard bounded over 24/7 operation."""
        self._essentials_nudge_days = {
            k: v for k, v in self._essentials_nudge_days.items() if k[1] == today
        }

    # --- #363 PII retention sweep -----------------------------------------
    def _run_pii_retention(self, now: datetime) -> int:
        """Prune PII older than the configured window, at most once per UTC day.

        Gated on ``retention_schedule`` — ``off``/empty (default) is a dormant no-op.
        Once-per-day idempotent (re-ticking the same day skips). Returns the count of
        PII rows pruned (0 when disabled / gated / already-run).
        """
        if self._retention is None or self._retention_schedule == "off":
            return 0
        today = now.date()
        if self._retention_days.get(today):
            return 0
        try:
            result = self._retention.prune_pii_older_than()
            pruned = int(result.get("pruned", 0))
            if pruned:
                log.info("pii_retention_swept", pruned=pruned)
        except Exception:  # pragma: no cover — retention must never break a tick
            log.warning("pii_retention_sweep_failed", exc_info=True)
            return 0
        finally:
            self._retention_days[today] = True
        return pruned

    def _active_campaigns(self, storage=None):
        store = storage or self._storage
        return [c for c in store.campaigns.list() if getattr(c, "active", True)]
