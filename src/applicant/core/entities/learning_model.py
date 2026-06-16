"""LearningModel entity — per-campaign learning state (FR-LEARN-*)."""

from __future__ import annotations

from dataclasses import dataclass, field

from applicant.core.ids import CampaignId


@dataclass(frozen=True)
class LearningModel:
    """Per-campaign learning state biasing discovery/scoring/selection.

    Kept cheap (statistical/local-embedding); LLM reserved for human-readable
    summaries (FR-LEARN-7).
    """

    campaign_id: CampaignId
    source_weights: dict = field(default_factory=dict)  # FR-DISC-5 source-yield
    converting_role_signature: dict = field(default_factory=dict)  # FR-LEARN-5
    exploration_budget: float = 0.1  # FR-LEARN-6
    feature_stats: dict = field(default_factory=dict)
