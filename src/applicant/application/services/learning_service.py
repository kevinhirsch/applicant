"""LearningService (FR-LEARN-*).

# STAGE B — owned by Phase 1 (v1) / Phase 4 (depth); flesh out here.

Per-campaign learning from every input; cheap statistical/local-embedding methods,
LLM reserved for human-readable summaries (FR-LEARN-7). Stub until Phase 1.
"""

from __future__ import annotations

from applicant.core.entities.learning_model import LearningModel
from applicant.core.ids import CampaignId


class LearningService:
    def __init__(self, storage, embedding) -> None:
        self._storage = storage
        self._embedding = embedding

    def model_for(self, campaign_id: CampaignId) -> LearningModel:
        return LearningModel(campaign_id=campaign_id)
