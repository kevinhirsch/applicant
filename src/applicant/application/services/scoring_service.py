"""ScoringService (FR-AGENT-3, FR-RESUME-7).

# STAGE B — owned by Phase 1 (viability) / Phase 3 (resume-fit); flesh out here.

Viability scoring from the JD (distinct from resume-fit coverage). Stub until P1.
"""

from __future__ import annotations

from applicant.core.entities.viability_scoring import ViabilityScoring
from applicant.core.ids import JobPostingId


class ScoringService:
    def __init__(self, storage, llm, embedding) -> None:
        self._storage = storage
        self._llm = llm
        self._embedding = embedding

    def score_viability(self, posting_id: JobPostingId) -> ViabilityScoring:
        # STAGE B: local-first viability scoring; LLM only when needed (NFR-TOKEN-1).
        return ViabilityScoring(posting_id=posting_id, score=0.0, rationale="not scored (Stage B)")
