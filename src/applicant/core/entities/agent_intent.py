"""AgentIntent entity — the single next-action sentence per run (FR-AGENT-7)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from applicant.core.ids import AgentRunId, CampaignId


@dataclass(frozen=True)
class AgentIntent:
    """One-sentence "what I intend to do next" recorded per agent run."""

    id: AgentRunId
    campaign_id: CampaignId
    intent_sentence: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
