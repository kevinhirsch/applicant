"""AgentRunService (FR-AGENT-1/2/7).

Agent run controls, persisted to ``campaigns`` + ``agent_runs``:

- **Tunable throughput** (FR-AGENT-1): ~15/day default, hard cap 30/day; any requested
  target is clamped to [1, 30] by the core ``clamp_throughput`` rule.
- **Run modes** (FR-AGENT-2): 24/7 continuous | fixed duration | until N viable roles —
  selectable per campaign and recorded on each run.
- **Per-run intent sentence** (FR-AGENT-7): each run logs a single sentence about what it
  intends to do next, stored on the ``agent_runs`` row.

``should_continue`` evaluates the stop condition for the active run mode so the durable
worker loop (Phase 2 wires it to DBOS scheduling) knows when to stop.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta

from applicant.core.entities.agent_run import AgentRun
from applicant.core.entities.campaign import Campaign, RunMode, clamp_throughput
from applicant.core.errors import InvalidInput, NotFound
from applicant.core.ids import AgentRunId, CampaignId, new_id


class AgentRunService:
    def __init__(self, storage, *, realtime=None) -> None:
        self._storage = storage
        # RT Phase 3 (realtime-websocket.md): an optional ``(mtype, data) -> None``
        # publisher that fans a downstream ``agent`` frame whenever a run is recorded,
        # so the operator's live tabs see the running agent's progress in realtime.
        # BE→FE surfacing ONLY — it never authorizes an upstream command. ``None``
        # (legacy construction / unit tests) is byte-identical: no push, no behavior
        # change. Injected once by the container into every AgentRunService build
        # (main + per-tick + per-request); the module-global realtime registry it
        # publishes to survives the scheduler's per-tick service rebuilds.
        self._realtime = realtime

    # --- run-control configuration (FR-AGENT-1/2) -------------------------
    def configure_run(
        self,
        campaign_id: CampaignId,
        *,
        run_mode: RunMode | str | None = None,
        throughput_target: int | None = None,
        schedule: dict | None = None,
    ) -> Campaign:
        """Set run mode + throughput (clamped to the hard cap) on the campaign."""
        campaign = self._storage.campaigns.get(campaign_id)
        if campaign is None:
            raise NotFound(f"campaign not found: {campaign_id}")
        patch: dict = {}
        if run_mode is not None:
            if isinstance(run_mode, str):
                try:
                    patch["run_mode"] = RunMode(run_mode)
                except ValueError as exc:
                    raise InvalidInput(
                        f"invalid run_mode {run_mode!r}: expected one of "
                        f"{[m.value for m in RunMode]}"
                    ) from exc
            else:
                patch["run_mode"] = run_mode
        if throughput_target is not None:
            patch["throughput_target"] = clamp_throughput(throughput_target)
        if schedule is not None:
            merged = dict(campaign.schedule or {})
            merged.update(schedule)
            patch["schedule"] = merged
        updated = dataclasses.replace(campaign, **patch)
        self._storage.campaigns.add(updated)
        self._storage.commit()
        return updated

    def set_active(self, campaign_id: CampaignId, active: bool) -> Campaign:
        """Pause/resume a campaign's automated work at runtime (NFR-ZEROCLI-1).

        Flips the persisted ``active`` flag: a paused (``active=False``) campaign is
        skipped by ``Scheduler._active_campaigns`` and short-circuited by
        ``should_continue``, so the 24/7 loop starts no new work for it — without a
        restart or any CLI. Resume re-includes it on the next tick. Persisted, so the
        pause survives restarts.
        """
        campaign = self._storage.campaigns.get(campaign_id)
        if campaign is None:
            raise NotFound(f"campaign not found: {campaign_id}")
        updated = dataclasses.replace(campaign, active=bool(active))
        self._storage.campaigns.add(updated)
        self._storage.commit()
        return updated

    # --- per-run intent (FR-AGENT-7) --------------------------------------
    def start_run(
        self, campaign_id: CampaignId, intent_sentence: str, *, stats: dict | None = None
    ) -> AgentRun:
        """Record an agent run with its single-sentence next-action intent.

        Raises :class:`NotFound` when the campaign does not exist (consistent with
        ``configure_run``) so a run is never silently recorded against a missing
        campaign.
        """
        campaign = self._storage.campaigns.get(campaign_id)
        if campaign is None:
            raise NotFound(f"campaign not found: {campaign_id}")
        run = AgentRun(
            id=AgentRunId(new_id()),
            campaign_id=campaign_id,
            intent_sentence=intent_sentence,
            run_mode=campaign.run_mode,
            throughput_target=campaign.throughput_target,
            stats=dict(stats or {}),
            # FR-AGENT-7: derive the tie-break ``seq`` from the max PERSISTED seq for
            # this campaign so it stays monotonic across restarts. The process-local
            # ``itertools.count`` resets to 1 on restart, which would let a brand-new
            # run at an equal timestamp lose the tie-break to a stale persisted run.
            seq=self._next_seq(campaign_id),
        )
        self._storage.agent_runs.add(run)
        self._storage.commit()
        self._prune_old_runs(campaign_id)
        self._publish_run_event(run)
        return run

    def _publish_run_event(self, run: AgentRun) -> None:
        """Fan a downstream ``agent`` frame for a just-recorded run (RT Phase 3).

        Carries the run's plain-language intent sentence + stats so a live tab can
        render the running agent's progress without polling; a reconnecting tab
        replays the ``agent`` channel buffer then goes live. No-op without a
        publisher (legacy/unit construction). Never raises — a transport hiccup
        must never break recording a run mid-tick.
        """
        if self._realtime is None:
            return
        try:
            self._realtime(
                "event",
                {
                    "campaign_id": str(run.campaign_id),
                    "intent": run.intent_sentence,
                    "stats": dict(run.stats or {}),
                    "run_mode": run.run_mode.value,
                    "run_seq": run.seq,
                },
            )
        except Exception:  # pragma: no cover - surfacing must never break the tick
            pass

    #: Rolling window of agent runs kept per campaign (#11 retention). Older runs are
    #: pruned so the ``agent_runs`` table does not grow unbounded under 24/7 ticking.
    RUN_RETENTION = 500

    def _prune_old_runs(self, campaign_id: CampaignId) -> None:
        """Prune agent runs beyond the rolling retention window (#11).

        Uses the indexed ``AgentRunRepository.prune_old`` (keeps the newest
        ``RUN_RETENTION`` runs per campaign, deletes the rest). Best-effort: retention
        must never break recording a run.
        """
        try:
            self._storage.agent_runs.prune_old(campaign_id, keep=self.RUN_RETENTION)
            self._storage.commit()
        except Exception:  # pragma: no cover - defensive
            pass

    def _next_seq(self, campaign_id: CampaignId) -> int:
        """Next monotonic seq = 1 + max persisted seq for the campaign (FR-AGENT-7, #11).

        Uses the indexed ``AgentRunRepository.max_seq`` (a single MAX query) instead of
        loading the campaign's ENTIRE run history every ``start_run``.
        """
        try:
            return int(self._storage.agent_runs.max_seq(campaign_id) or 0) + 1
        except Exception:  # pragma: no cover - defensive
            return 1

    def list_runs(self, campaign_id: CampaignId) -> list[AgentRun]:
        return self._storage.agent_runs.list_for_campaign(campaign_id)

    def latest_intent(self, campaign_id: CampaignId) -> str | None:
        """Most-recent run's intent (FR-AGENT-7, #11).

        Uses the indexed ``AgentRunRepository.latest`` (ORDER BY (timestamp, seq) ...
        LIMIT 1) instead of scanning every run.
        """
        run = self._storage.agent_runs.latest(campaign_id)
        return run.intent_sentence if run is not None else None

    def status(self, campaign_id: CampaignId, *, now: datetime | None = None) -> dict:
        """Live per-campaign agent status for the operator (FR-AGENT-7/FR-OBS-2).

        Combines the persisted run config (mode/throughput/active) with the latest
        run's intent + stats and today's applied-count vs the daily budget, so the
        front-door can answer 'is the agent working, and what has it done today'.
        """
        now = now or datetime.now(UTC)
        campaign = self._storage.campaigns.get(campaign_id)
        if campaign is None:
            raise NotFound(f"campaign not found: {campaign_id}")
        latest = self._storage.agent_runs.latest(campaign_id)
        try:
            applied_today = int(
                self._storage.agent_runs.count_pipelines_started_on(campaign_id, now.date())
            )
        except Exception:  # pragma: no cover - defensive: count is best-effort
            applied_today = 0
        return {
            "campaign_id": str(campaign_id),
            "active": bool(campaign.active),
            "paused": not bool(campaign.active),
            "run_mode": campaign.run_mode.value,
            "throughput_target": campaign.throughput_target,
            "daily_budget": clamp_throughput(campaign.throughput_target),
            "applied_today": applied_today,
            "latest_intent": latest.intent_sentence if latest is not None else None,
            "latest_stats": dict(latest.stats) if latest is not None else {},
            "last_run_at": (
                latest.timestamp.isoformat()
                if latest is not None and latest.timestamp is not None
                else None
            ),
        }

    # --- run-mode stop condition (FR-AGENT-2) -----------------------------
    def should_continue(
        self,
        campaign: Campaign,
        *,
        started_at: datetime | None = None,
        now: datetime | None = None,
        viable_count: int = 0,
    ) -> bool:
        """Whether the run loop should keep going under the campaign's run mode.

        - CONTINUOUS: always (24/7) — the loop is bounded only by throughput.
        - FIXED_DURATION: until ``schedule['duration_minutes']`` elapses.
        - UNTIL_N_VIABLE: until ``viable_count`` reaches ``schedule['target_viable']``.
        """
        if not campaign.active:
            return False
        if campaign.run_mode is RunMode.CONTINUOUS:
            return True
        if campaign.run_mode is RunMode.FIXED_DURATION:
            minutes = int((campaign.schedule or {}).get("duration_minutes", 0))
            if minutes <= 0 or started_at is None:
                return True
            now = now or datetime.now(UTC)
            return now < started_at + timedelta(minutes=minutes)
        if campaign.run_mode is RunMode.UNTIL_N_VIABLE:
            target = int((campaign.schedule or {}).get("target_viable", 0))
            if target <= 0:
                return True
            return viable_count < target
        return True

    def daily_budget(self, campaign: Campaign) -> int:
        """The effective per-day application budget (clamped, FR-AGENT-1)."""
        return clamp_throughput(campaign.throughput_target)
