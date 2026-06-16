"""LearningService (FR-LEARN-1/3/4/5/6/7, FR-DISC-5).

# STAGE B — owned by Phase 1 (v1) / Phase 4 (depth).

Per-campaign learning v1, kept deliberately **cheap** (statistical + local embeddings;
no LLM in the hot path, FR-LEARN-7):

- **Source-yield learning** (FR-DISC-5, FR-LEARN-6): maintain a decayed yield weight per
  discovery source so high-yielding sources are favored on the next run.
- **Exploration budget** (FR-LEARN-6): reserve a fraction of effort for under-sampled /
  new sources so the system never collapses onto a single source.
- **Decline-feedback ingestion** (FR-LEARN-1/3): fold approve/decline signals into
  per-feature stats biasing future scoring.

State lives on the immutable ``LearningModel`` entity; every method returns a new model
(pure-functional update), so the service holds no hidden mutable state.
"""

from __future__ import annotations

from dataclasses import replace

from applicant.core.entities.learning_model import LearningModel
from applicant.core.ids import CampaignId

#: Exponential decay applied to prior yield weight before folding in a new run.
_DECAY = 0.7


class LearningService:
    def __init__(self, storage, embedding) -> None:
        self._storage = storage
        self._embedding = embedding

    def model_for(self, campaign_id: CampaignId) -> LearningModel:
        return LearningModel(campaign_id=campaign_id)

    # --- source-yield learning (FR-DISC-5 / FR-LEARN-6) -------------------
    def record_source_yield(
        self, model: LearningModel, yields: dict[str, int]
    ) -> LearningModel:
        """Fold per-source yield counts into decayed source weights."""
        weights = dict(model.source_weights)
        for key in set(weights) | set(yields):
            prior = weights.get(key, 0.0)
            weights[key] = prior * _DECAY + float(yields.get(key, 0))
        return replace(model, source_weights=weights)

    def source_ranking(self, model: LearningModel) -> list[str]:
        """Sources ordered by learned yield weight, highest first (FR-DISC-5)."""
        return [k for k, _ in sorted(model.source_weights.items(), key=lambda kv: -kv[1])]

    def exploration_split(
        self, model: LearningModel, all_sources: list[str]
    ) -> tuple[list[str], list[str]]:
        """Partition sources into (exploit, explore).

        Unseen / zero-weight sources go to the explore set; the budget caps how much
        of the effort goes to exploration so a single source never monopolizes runs
        (FR-LEARN-6).
        """
        ranked = self.source_ranking(model)
        unseen = [s for s in all_sources if s not in model.source_weights]
        # Anything with weight but ranked low is also fair game for exploration.
        explore = unseen[:] or ranked[-1:] if ranked else unseen
        budget = max(0.0, min(1.0, model.exploration_budget))
        max_explore = max(1, int(round(len(all_sources) * budget))) if all_sources else 0
        explore = explore[:max_explore]
        exploit = [s for s in (ranked or all_sources) if s not in explore]
        return exploit, explore

    # --- feedback ingestion (FR-LEARN-1/3) --------------------------------
    def record_decision(
        self, model: LearningModel, *, approved: bool, features: dict | None = None
    ) -> LearningModel:
        """Fold an approve/decline signal into per-feature stats (cheap)."""
        stats = {k: dict(v) for k, v in model.feature_stats.items()}
        bucket = "approve" if approved else "decline"
        for feat, val in (features or {}).items():
            slot = stats.setdefault(feat, {})
            label = f"{val}:{bucket}"
            slot[label] = slot.get(label, 0) + 1
        return replace(model, feature_stats=stats)
