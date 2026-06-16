"""DiscoveryService (FR-DISC-*, NFR-TOKEN-1).

# STAGE B — owned by Phase 1.

Coordinates the Discovery + Embedding ports: runs the master aggregator over enabled
sources, dedups near-duplicate postings via local embeddings (NFR-LOCAL-1), persists
the survivors campaign-scoped, and records per-source yield so the LearningService can
bias future runs (FR-DISC-5). Structured scraping incurs zero LLM tokens (FR-DISC-4).
"""

from __future__ import annotations

from applicant.core.entities.job_posting import JobPosting
from applicant.core.entities.search_criteria import SearchCriteria
from applicant.core.ids import CampaignId

#: Cosine similarity above which two postings are treated as duplicates.
_DEDUP_THRESHOLD = 0.97


class DiscoveryService:
    def __init__(self, storage, discovery, embedding) -> None:
        self._storage = storage
        self._discovery = discovery
        self._embedding = embedding

    def run_discovery(
        self, campaign_id: CampaignId, criteria: SearchCriteria | None = None
    ) -> list[JobPosting]:
        """Search enabled sources, dedup, persist, return the kept postings."""
        criteria = criteria or SearchCriteria(campaign_id=campaign_id)
        raw = self._discovery.search(campaign_id, criteria)
        kept = self._dedup(raw)
        for posting in kept:
            self._storage.postings.add(posting)
        self._storage.commit()
        return kept

    def source_yield(self, postings: list[JobPosting]) -> dict[str, int]:
        """Count postings per source-key for FR-DISC-5 source-yield learning."""
        counts: dict[str, int] = {}
        for p in postings:
            key = p.source_key or "unknown"
            counts[key] = counts.get(key, 0) + 1
        return counts

    def _dedup(self, postings: list[JobPosting]) -> list[JobPosting]:
        kept: list[JobPosting] = []
        for candidate in postings:
            sig = f"{candidate.title} {candidate.company}"
            if any(
                self._embedding.similarity(sig, f"{k.title} {k.company}") >= _DEDUP_THRESHOLD
                for k in kept
            ):
                continue
            kept.append(candidate)
        return kept
