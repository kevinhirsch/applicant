"""DiscoveryService (FR-DISC-*, NFR-TOKEN-1).

Coordinates the Discovery + Embedding ports + the persisted source registry:

- seeds/loads per-campaign **source toggles** from ``discovery_sources`` and applies
  them to the master aggregator (FR-DISC-2);
- runs the aggregator over enabled sources, dedups near-duplicate postings via local
  embeddings (NFR-LOCAL-1), persists survivors campaign-scoped;
- records **per-source yield** (matches this run) into ``discovery_sources.yield_stats``
  via the LearningService so future runs reweight toward high-yield sources (FR-DISC-5).

Structured scraping incurs zero LLM tokens (FR-DISC-4).
"""

from __future__ import annotations

from applicant.core.entities.discovery_source import DiscoverySource
from applicant.core.entities.job_posting import JobPosting
from applicant.core.entities.search_criteria import SearchCriteria
from applicant.core.ids import CampaignId, DiscoverySourceId, new_id

#: Cosine similarity above which two postings are treated as duplicates.
_DEDUP_THRESHOLD = 0.97


class DiscoveryService:
    def __init__(self, storage, discovery, embedding, learning=None) -> None:
        self._storage = storage
        self._discovery = discovery
        self._embedding = embedding
        self._learning = learning  # optional LearningService for yield persistence

    # --- source registry (FR-DISC-2) --------------------------------------
    def sync_registry(self, campaign_id: CampaignId) -> list[DiscoverySource]:
        """Reconcile the adapter's available sources with persisted toggles.

        New adapter sources are seeded enabled (FR-DISC-2 extensible: a new source
        adapter shows up without core changes); persisted toggles are applied back to
        the adapter so a disabled source stays disabled across runs.
        """
        persisted = {
            s.source_key: s
            for s in self._storage.discovery_sources.list_for_campaign(campaign_id)
        }
        for key in self._discovery.available_sources():
            if key not in persisted:
                rec = DiscoverySource(
                    id=DiscoverySourceId(new_id()),
                    campaign_id=campaign_id,
                    source_key=key,
                    enabled=self._discovery.is_source_enabled(key),
                )
                self._storage.discovery_sources.upsert(rec)
                persisted[key] = rec
        self._storage.commit()
        # Apply persisted toggles back onto the adapter.
        self._discovery.apply_toggles({k: v.enabled for k, v in persisted.items()})
        return list(persisted.values())

    def set_source_enabled(
        self, campaign_id: CampaignId, source_key: str, enabled: bool
    ) -> None:
        """User-selectable toggle, persisted to ``discovery_sources`` (FR-DISC-2)."""
        existing = self._storage.discovery_sources.get(campaign_id, source_key)
        rec = DiscoverySource(
            id=existing.id if existing else DiscoverySourceId(new_id()),
            campaign_id=campaign_id,
            source_key=source_key,
            enabled=enabled,
            yield_stats=existing.yield_stats if existing else {},
        )
        self._storage.discovery_sources.upsert(rec)
        self._storage.commit()
        if source_key in self._discovery.available_sources():
            self._discovery.set_source_enabled(source_key, enabled)

    def list_sources(self, campaign_id: CampaignId) -> list[DiscoverySource]:
        return self._storage.discovery_sources.list_for_campaign(campaign_id)

    # --- discovery run ----------------------------------------------------
    def run_discovery(
        self, campaign_id: CampaignId, criteria: SearchCriteria | None = None
    ) -> list[JobPosting]:
        """Search enabled sources, dedup, persist, record yield, return kept postings."""
        criteria = criteria or SearchCriteria(campaign_id=campaign_id)
        self.sync_registry(campaign_id)
        raw = self._discovery.search(campaign_id, criteria)
        kept = self._dedup(raw)
        for posting in kept:
            self._storage.postings.add(posting)
        self._storage.commit()
        self._record_yield(campaign_id, kept)
        return kept

    def source_yield(self, postings: list[JobPosting]) -> dict[str, int]:
        """Count postings per source-key for FR-DISC-5 source-yield learning."""
        counts: dict[str, int] = {}
        for p in postings:
            key = p.source_key or "unknown"
            counts[key] = counts.get(key, 0) + 1
        return counts

    def _record_yield(self, campaign_id: CampaignId, postings: list[JobPosting]) -> None:
        if self._learning is None:
            return
        counts = self.source_yield(postings)
        model = self._learning.load_model(campaign_id)
        model = self._learning.record_source_funnel(
            model, {k: {"matches": v} for k, v in counts.items()}
        )
        self._learning.persist_model(model)

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
