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
    def __init__(self, storage, discovery, embedding, learning=None, tool_registry=None) -> None:
        self._storage = storage
        self._discovery = discovery
        self._embedding = embedding
        self._learning = learning  # optional LearningService for yield persistence
        self._tools = tool_registry  # optional ToolRegistry for FR-UI-4 dispatch gate

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
        """Search enabled sources, dedup, persist, record yield, return kept postings.

        Honors the Discovery tool toggle (FR-UI-4): when disabled, dispatch is
        blocked with a clear reason and nothing is searched.
        """
        if self._tools is not None:
            self._tools.ensure_enabled("discovery")
        criteria = criteria or SearchCriteria(campaign_id=campaign_id)
        criteria = self._bias_criteria_toward_converting(campaign_id, criteria)
        self.sync_registry(campaign_id)
        order = self._prioritized_sources(campaign_id)
        raw = (
            self._discovery.search(campaign_id, criteria, sources=order)
            if order is not None
            else self._discovery.search(campaign_id, criteria)
        )
        kept = self._dedup(raw)
        for posting in kept:
            self._storage.postings.add(posting)
        self._storage.commit()
        self._record_yield(campaign_id, kept)
        return kept

    def _bias_criteria_toward_converting(
        self, campaign_id: CampaignId, criteria: SearchCriteria
    ) -> SearchCriteria:
        """Bias discovery titles toward the converting-role's titles (FR-LEARN-5).

        When learning has recorded which roles actually convert, fold those titles
        into the search criteria so discovery leans toward the converting role's
        titles/sources. New titles are appended (never replacing the user's), so the
        user's stated criteria are still honored.
        """
        if self._learning is None:
            return criteria
        try:
            model = self._learning.load_model(campaign_id)
            converting = self._learning.converting_titles(model)
        except Exception:  # pragma: no cover - defensive
            return criteria
        if not converting:
            return criteria
        import dataclasses

        merged = list(criteria.titles)
        for t in converting:
            if t not in merged:
                merged.append(t)
        if len(merged) == len(criteria.titles):
            return criteria
        return dataclasses.replace(criteria, titles=tuple(merged))

    def _prioritized_sources(self, campaign_id: CampaignId) -> list[str] | None:
        """Order enabled sources by learned yield + reserve the exploration budget.

        FR-DISC-5/FR-LEARN-6: discovery no longer treats enabled sources as a flat
        boolean set. The LearningService's ``source_ranking`` puts high-conversion
        sources first (exploit), and ``exploration_split`` reserves a fraction of the
        run for under-used / cold sources so the system keeps probing new sources and
        never collapses onto one. Returns an ordered list of enabled source keys, or
        ``None`` when no learning is wired (legacy: query every enabled source).
        """
        if self._learning is None:
            return None
        enabled = list(self._discovery.enabled_sources()) if hasattr(
            self._discovery, "enabled_sources"
        ) else list(self._discovery.available_sources())
        if not enabled:
            return None
        model = self._learning.load_model(campaign_id)
        exploit, explore = self._learning.exploration_split(model, enabled)
        # High-yield exploit sources first (ranking order), then the exploration
        # probes; keep only enabled keys, de-duped, preserving order.
        ordered: list[str] = []
        for key in [*exploit, *explore]:
            if key in enabled and key not in ordered:
                ordered.append(key)
        # Any enabled source not placed by the split still gets queried (so a brand
        # new enabled source is never silently dropped before it has stats).
        for key in enabled:
            if key not in ordered:
                ordered.append(key)
        return ordered

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
        # Atomic per-campaign fold so concurrent approval/submission recording can't
        # lose-update the shared learning state (FR-LEARN-1/FR-DUR-2).
        self._learning.record_funnel_atomic(
            campaign_id, {k: {"matches": v} for k, v in counts.items()}
        )

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
