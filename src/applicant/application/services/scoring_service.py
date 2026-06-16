"""ScoringService (FR-AGENT-3).

# STAGE B — owned by Phase 1 (viability) / Phase 3 (resume-fit).

Viability scoring from the JD: *can the user reasonably get this role?* — distinct from
resume-fit coverage (FR-RESUME-7, Phase 3). Local-first and zero-token by default
(NFR-TOKEN-1): a cheap deterministic signal over criteria/JD overlap via local
embeddings; the LLM port is reserved for genuinely ambiguous cases (not invoked here).

The viability **threshold defaults to 70** (on a 0..100 scale) and is configurable per
campaign; ``is_viable`` gates which postings reach the digest.
"""

from __future__ import annotations

from applicant.core.entities.job_posting import JobPosting
from applicant.core.entities.search_criteria import SearchCriteria
from applicant.core.entities.viability_scoring import ViabilityScoring
from applicant.core.ids import JobPostingId

#: Default viability threshold on a 0..100 scale (FR-AGENT-3); configurable.
DEFAULT_VIABILITY_THRESHOLD = 70


class ScoringService:
    def __init__(self, storage, llm, embedding, *, threshold: int = DEFAULT_VIABILITY_THRESHOLD) -> None:
        self._storage = storage
        self._llm = llm
        self._embedding = embedding
        self._threshold = threshold

    @property
    def threshold(self) -> int:
        return self._threshold

    def score_viability(
        self, posting_id: JobPostingId, criteria: SearchCriteria | None = None
    ) -> ViabilityScoring:
        """Score a stored posting against the campaign criteria (local-first)."""
        posting = self._storage.postings.get(posting_id)
        if posting is None:
            return ViabilityScoring(posting_id=posting_id, score=0.0, rationale="posting not found")
        return self._score(posting, criteria)

    def score_posting(
        self, posting: JobPosting, criteria: SearchCriteria | None = None
    ) -> ViabilityScoring:
        """Score an in-hand posting (no storage round-trip)."""
        return self._score(posting, criteria)

    def is_viable(self, scoring: ViabilityScoring) -> bool:
        """True if the scaled (0..100) score meets the configurable threshold."""
        return scoring.score * 100.0 >= self._threshold

    def _score(self, posting: JobPosting, criteria: SearchCriteria | None) -> ViabilityScoring:
        if criteria is None:
            criteria = SearchCriteria(campaign_id=posting.campaign_id)
        criteria_text = " ".join(
            (*criteria.titles, *criteria.keywords, criteria.human_readable)
        ).strip()
        jd_text = f"{posting.title} {posting.description}".strip()
        if not criteria_text:
            # No stated criteria yet: neutral-positive so nothing is silently dropped.
            score = 0.75
            rationale = "no criteria stated; neutral viability (FR-AGENT-3 default)"
        else:
            score = self._embedding.similarity(criteria_text, jd_text)
            rationale = (
                f"local viability {score * 100:.0f}/100 from JD/criteria overlap "
                f"(threshold {self._threshold}; zero-token, FR-AGENT-3/NFR-TOKEN-1)"
            )
        return ViabilityScoring(posting_id=posting.id, score=score, rationale=rationale)
