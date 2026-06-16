"""AgentRun entity — a single discovery/processing run with its intent (FR-AGENT-1/2/7)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from applicant.core.entities.campaign import RunMode
from applicant.core.ids import AgentRunId, CampaignId


@dataclass(frozen=True)
class AgentRun:
    """One agent run, persisted to ``agent_runs``.

    Carries the single-sentence next-action intent (FR-AGENT-7) plus the run-control
    snapshot (mode + throughput) that governed it (FR-AGENT-1/2). ``stats`` records
    what the run actually did (e.g. processed/viable counts) for run-mode stop checks.
    """

    id: AgentRunId
    campaign_id: CampaignId
    intent_sentence: str = ""
    run_mode: RunMode = RunMode.CONTINUOUS
    throughput_target: int = 15
    stats: dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
