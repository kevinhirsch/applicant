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

import time
from collections.abc import Callable

from applicant.core.entities.discovery_source import DiscoverySource
from applicant.core.entities.job_posting import JobPosting
from applicant.core.entities.search_criteria import SearchCriteria
from applicant.core.events import JobDiscovered, event_bus
from applicant.core.ids import CampaignId, DiscoverySourceId, new_id
from applicant.core.rules.source_pacing import (
    DEFAULT_PER_DOMAIN_INTERVAL_SECONDS,
    SourcePacer,
)

#: Cosine similarity above which two postings are treated as duplicates.
_DEDUP_THRESHOLD = 0.97

#: Hard ceiling on the TOTAL time one ``run_discovery`` call may spend waiting on
#: per-domain pacing (#195, dark-engine audit item 49). Pacing is a best-effort
#: anti-bot smoothing, not a hard guarantee -- a burst on one domain large enough to
#: need more than this degrades to immediate (unpaced) emission for the remainder
#: rather than stalling a scheduler tick indefinitely (never hangs unboundedly).
_MAX_TOTAL_PACE_WAIT_SECONDS = 10.0


class DiscoveryService:
    def __init__(
        self,
        storage,
        discovery,
        embedding,
        learning=None,
        tool_registry=None,
        *,
        advanced_learning=None,
        source_pacer: SourcePacer | None = None,
        per_domain_interval_seconds: float = DEFAULT_PER_DOMAIN_INTERVAL_SECONDS,
        pace_clock: Callable[[], float] = time.monotonic,
        pace_sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._storage = storage
        self._discovery = discovery
        self._embedding = embedding
        # Per-job-board (per-domain) request pacer (#195). A process-scoped pacer can be
        # injected so the per-domain interval survives the per-tick service rebuild;
        # otherwise a fresh one is created with the configured interval.
        self._source_pacer = source_pacer or SourcePacer(
            interval_seconds=per_domain_interval_seconds
        )
        # Injectable clock/sleep so ``_apply_pacing`` (below) is deterministically
        # testable without real wall-clock delay; production uses the real clock.
        self._pace_clock = pace_clock
        self._pace_sleep = pace_sleep
        self._learning = learning  # optional LearningService for yield persistence
        # Optional AdvancedLearningService so discovery can also lean toward titles
        # mined from the DISCRETE converting signature the live loop writes, plus an
        # advisory recall probe for "roles like the ones that converted" (FR-LEARN-5 /
        # FR-MIND-3). ``None`` (default) => no extra title bias, byte-identical.
        self._advanced_learning = advanced_learning
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
        # Load previously persisted postings for cross-run dedup (#196).
        existing = list(self._storage.postings.list_for_campaign(campaign_id))
        kept = self._dedup(raw, existing=existing)
        # #195/dark-engine-49: space same-domain postings under the anti-bot interval
        # before they're processed further, so a burst from one job-board domain
        # doesn't hammer it. Postings on different domains are never mutually delayed.
        self._apply_pacing(kept)
        for posting in kept:
            self._storage.postings.add(posting)
            event_bus.emit(
                JobDiscovered(
                    campaign_id=campaign_id,
                    posting_id=posting.id,
                )
            )
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
        converting: list[str] = []
        # Phase-1 centroid titles (populated by record_converting_role).
        if self._learning is not None:
            try:
                model = self._learning.load_model(campaign_id)
                converting.extend(self._learning.converting_titles(model))
            except Exception:  # pragma: no cover - defensive
                pass
        # DISCRETE-signature titles the LIVE conversion loop actually writes, plus a
        # bounded advisory recall probe (FR-LEARN-5 / FR-MIND-3). Distinct sources from
        # the centroid, merged + de-duped below — never re-folded, so no double-count.
        if self._advanced_learning is not None:
            try:
                adv_model = self._advanced_learning.load_model(campaign_id)
                converting.extend(self._advanced_learning.converting_titles(adv_model))
            except Exception:  # pragma: no cover - defensive
                pass
            try:
                converting.extend(self._advanced_learning.recall_titles(campaign_id))
            except Exception:  # pragma: no cover - defensive
                pass
        if not converting:
            return criteria
        import dataclasses

        # Preserve the user's titles verbatim; APPEND learned titles (case-insensitive
        # de-dup) so the user's stated criteria are never replaced, only widened.
        merged = list(criteria.titles)
        seen = {t.strip().lower() for t in merged}
        for t in converting:
            key = (t or "").strip().lower()
            if key and key not in seen:
                merged.append(t)
                seen.add(key)
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

    def pace_schedule(
        self, postings: list[JobPosting], *, start: float = 0.0
    ) -> list[tuple[JobPosting, float]]:
        """Pace per-board requests under the configurable per-domain interval (#195).

        Given postings discovered in one run, assign each a release time that keeps
        successive requests to the SAME job-board domain at least ``interval_seconds``
        apart, so a burst from one domain (e.g. ten ``linkedin.com`` postings) is
        spread out below the anti-bot ceiling. Returns ``(posting, release_at)`` pairs
        in input order; postings on different domains are independent and never delay
        each other. Pure scheduling (the caller decides whether/how to wait), so it is
        deterministic and side-effect-free apart from advancing the pacer's per-domain
        last-allowed marks.
        """
        scheduled: list[tuple[JobPosting, float]] = []
        for posting in postings:
            url = getattr(posting, "source_url", "") or ""
            release = max(start, self._source_pacer.next_allowed_at(url))
            self._source_pacer.record(url, release)
            scheduled.append((posting, release))
        return scheduled

    def _apply_pacing(self, postings: list[JobPosting]) -> None:
        """Enforce :meth:`pace_schedule` for real (dark-engine audit item 49).

        ``pace_schedule`` is pure ("the caller decides whether/how to wait") — this is
        that caller. Anchored at the real clock (``start=self._pace_clock()``) so a
        posting that is FIRST for its domain releases immediately, and a later posting
        on the SAME domain releases ``interval_seconds`` after the previous one;
        postings on different domains always compute ``release <= start`` and so never
        wait on each other (see ``SourcePacer.next_allowed_at``).

        Bounded: the total time this call may spend sleeping is capped at
        ``_MAX_TOTAL_PACE_WAIT_SECONDS`` — once that budget is spent the remaining
        postings in this run are emitted immediately rather than blocking the caller
        (a scheduler tick) indefinitely on a large same-domain burst.
        """
        if not postings:
            return
        start = self._pace_clock()
        schedule = self.pace_schedule(postings, start=start)
        budget = _MAX_TOTAL_PACE_WAIT_SECONDS
        for _posting, release_at in schedule:
            if budget <= 0:
                break
            wait = release_at - self._pace_clock()
            if wait <= 0:
                continue
            wait = min(wait, budget)
            self._pace_sleep(wait)
            budget -= wait

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

    def _dedup(
        self,
        postings: list[JobPosting],
        *,
        existing: list[JobPosting] | None = None,
    ) -> list[JobPosting]:
        """Dedup within a run AND across runs (FR-DISC-3, #196).

        Compares each candidate against postings already kept THIS run (cross-source
        within-run dedup) AND against previously persisted postings from earlier runs
        (cross-run dedup) so the same posting is never ingested twice across
        discovery schedule ticks.
        """
        baseline = list(existing) if existing else []
        kept: list[JobPosting] = []
        for candidate in postings:
            sig = f"{candidate.title} {candidate.company}"
            if any(
                self._embedding.similarity(sig, f"{k.title} {k.company}") >= _DEDUP_THRESHOLD
                for k in [*kept, *baseline]
            ):
                continue
            kept.append(candidate)
        return kept
