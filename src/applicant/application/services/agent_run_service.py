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
from applicant.core.ids import AgentRunId, CampaignId, new_id


class AgentRunService:
    def __init__(self, storage) -> None:
        self._storage = storage

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
            raise KeyError(f"campaign not found: {campaign_id}")
        patch: dict = {}
        if run_mode is not None:
            patch["run_mode"] = RunMode(run_mode) if isinstance(run_mode, str) else run_mode
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

    # --- per-run intent (FR-AGENT-7) --------------------------------------
    def start_run(
        self, campaign_id: CampaignId, intent_sentence: str, *, stats: dict | None = None
    ) -> AgentRun:
        """Record an agent run with its single-sentence next-action intent."""
        campaign = self._storage.campaigns.get(campaign_id)
        run = AgentRun(
            id=AgentRunId(new_id()),
            campaign_id=campaign_id,
            intent_sentence=intent_sentence,
            run_mode=campaign.run_mode if campaign else RunMode.CONTINUOUS,
            throughput_target=campaign.throughput_target if campaign else 15,
            stats=dict(stats or {}),
        )
        self._storage.agent_runs.add(run)
        self._storage.commit()
        return run

    def list_runs(self, campaign_id: CampaignId) -> list[AgentRun]:
        return self._storage.agent_runs.list_for_campaign(campaign_id)

    def latest_intent(self, campaign_id: CampaignId) -> str | None:
        runs = self._storage.agent_runs.list_for_campaign(campaign_id)
        if not runs:
            return None
        # FR-AGENT-7: tie-break on monotonic insertion ``seq`` so the truly-latest
        # run wins even when two runs share an identical timestamp (max(timestamp)
        # alone is unstable for equal keys).
        return max(runs, key=lambda r: (r.timestamp, r.seq)).intent_sentence

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
