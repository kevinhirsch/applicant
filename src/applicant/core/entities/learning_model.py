"""LearningModel entity — per-campaign learning state (FR-LEARN-*)."""

from __future__ import annotations

from dataclasses import dataclass, field

from applicant.core.ids import CampaignId


@dataclass(frozen=True)
class LearningModel:
    """Per-campaign learning state biasing discovery/scoring/selection.

    Kept cheap (statistical/local-embedding); LLM reserved for human-readable
    summaries (FR-LEARN-7).

    ``source_weights`` is the decayed scalar yield weight per source (FR-DISC-5).
    ``source_yield_stats`` is the richer per-source funnel (matches -> approvals ->
    submissions) that drives the weight and is persisted to ``discovery_sources``.
    ``converting_role_signature`` is the centroid-ish signature of roles that
    actually converted (approved + submitted), biasing future discovery/scoring
    (FR-LEARN-5). ``converting_samples`` is the running count behind the centroid.
    """

    campaign_id: CampaignId
    source_weights: dict = field(default_factory=dict)  # FR-DISC-5 source-yield
    source_yield_stats: dict = field(default_factory=dict)  # FR-DISC-5 funnel per source
    converting_role_signature: dict = field(default_factory=dict)  # FR-LEARN-5
    converting_samples: int = 0  # FR-LEARN-5 centroid sample count
    exploration_budget: float = 0.1  # FR-LEARN-6
    feature_stats: dict = field(default_factory=dict)
