"""LearningService (FR-LEARN-1/3/4/5/6/7, FR-DISC-5).

Per-campaign learning v1, kept deliberately **cheap** (statistical + local embeddings;
no LLM in the hot path, FR-LEARN-7):

- **Source-yield learning** (FR-DISC-5, FR-LEARN-6): track the per-source funnel
  matches -> approvals -> submissions, decay it over time, and derive a weight so
  high-yielding sources are favored and low-yielding ones down-weighted next run.
- **Exploration budget** (FR-LEARN-6): reserve a fraction of effort for under-sampled /
  new sources so the system never collapses onto one source, and periodically retry
  under-used sources.
- **Decline/approve-feedback ingestion** (FR-LEARN-1/3): fold approve/decline signals
  into per-feature stats biasing future scoring.
- **Converting-role signature** (FR-LEARN-5): maintain a running centroid embedding of
  the roles that actually convert (approved + submitted) so discovery + scoring can be
  biased toward that signature.

State lives on the immutable ``LearningModel`` entity; every method returns a new model
(pure-functional update), so the service holds no hidden mutable state. ``load_model`` /
``persist_*`` bridge that state to ``campaigns.learning_state`` + ``discovery_sources``.
"""

from __future__ import annotations

import dataclasses
import threading
from collections import defaultdict
from dataclasses import dataclass, field, replace

from applicant.core.entities.attribute import Attribute
from applicant.core.entities.discovery_source import DiscoverySource
from applicant.core.entities.learning_model import LearningModel
from applicant.core.ids import AttributeId, CampaignId, DiscoverySourceId, new_id
from applicant.core.rules.confirmation_gate import requires_confirmation
from applicant.core.rules.taste_bias import taste_bias


@dataclass(frozen=True)
class CrossReferenceResult:
    """Outcome of cross-referencing parsed input with the attribute cloud (FR-LEARN-4).

    ``applied`` are non-integral attributes auto-updated in place; ``pending`` are
    integral changes recorded for the user to confirm via the existing confirmation
    gate (FR-FB-3) — the engine never silently mutates a core attribute.
    """

    applied: list[Attribute] = field(default_factory=list)
    pending: list[dict] = field(default_factory=list)

#: Exponential decay applied to prior yield weight before folding in a new run.
_DECAY = 0.7
#: Funnel weights — a submission is worth more than an approval, an approval more
#: than a raw match (FR-DISC-5: conversion is the real target, not just volume).
_W_MATCH = 1.0
_W_APPROVAL = 5.0
_W_SUBMISSION = 12.0

#: #12: cap the per-campaign ``feature_stats`` JSONB blob so it does not grow
#: unbounded as it is rewritten on every fold. Keep only the top-N features by total
#: count; raw free-text feedback tokens (a ``free_text:`` namespace) are dropped
#: entirely — they are an unbounded vocabulary that bloats the blob without biasing.
_FEATURE_STATS_CAP = 200
_RAW_FEEDBACK_PREFIX = "free_text:"


def cap_feature_stats(
    stats: dict[str, dict], *, cap: int = _FEATURE_STATS_CAP
) -> dict[str, dict]:
    """Drop raw-feedback features + keep the top-N by total count (#12)."""
    if not stats:
        return {}
    # Drop the unbounded raw free-text token namespace outright.
    pruned = {k: v for k, v in stats.items() if not k.startswith(_RAW_FEEDBACK_PREFIX)}
    if len(pruned) <= cap:
        return pruned

    def _total(slot: dict) -> int:
        try:
            return sum(int(c) for c in slot.values())
        except Exception:  # pragma: no cover - defensive
            return 0

    top = sorted(pruned.items(), key=lambda kv: -_total(kv[1]))[:cap]
    return dict(top)


#: Per-campaign locks guarding the non-atomic load -> fold -> persist of shared
#: learning state (FR-LEARN-1/FR-DUR-2). Keyed by campaign id and shared across all
#: LearningService instances in-process so concurrent record paths (approvals/
#: submissions vs. discovery matches) can't lose an update under 24/7 + DBOS queues.
#: Hermetic + sufficient for the default lane; the SQL lane should additionally use a
#: row-locked transaction.
_CAMPAIGN_LOCKS: dict[str, threading.Lock] = defaultdict(threading.Lock)
_LOCKS_GUARD = threading.Lock()


def _campaign_lock(campaign_id: CampaignId) -> threading.Lock:
    with _LOCKS_GUARD:
        return _CAMPAIGN_LOCKS[str(campaign_id)]


class LearningService:
    def __init__(self, storage, embedding) -> None:
        self._storage = storage
        self._embedding = embedding

    def model_for(self, campaign_id: CampaignId) -> LearningModel:
        return LearningModel(campaign_id=campaign_id)

    # --- persistence bridge (FR-LEARN-1 per-campaign) ---------------------
    def load_model(self, campaign_id: CampaignId) -> LearningModel:
        """Rehydrate the learning model from persisted campaign + source state."""
        model = LearningModel(campaign_id=campaign_id)
        campaign = self._storage.campaigns.get(campaign_id)
        if campaign is not None:
            ls = dict(campaign.learning_state or {})
            model = replace(
                model,
                converting_role_signature=dict(ls.get("converting_role_signature", {})),
                converting_samples=int(ls.get("converting_samples", 0)),
                exploration_budget=float(ls.get("exploration_budget", campaign.exploration_budget)),
                feature_stats=dict(ls.get("feature_stats", {})),
            )
        weights: dict[str, float] = {}
        stats: dict[str, dict] = {}
        for src in self._storage.discovery_sources.list_for_campaign(campaign_id):
            ys = dict(src.yield_stats or {})
            stats[src.source_key] = ys
            weights[src.source_key] = float(ys.get("weight", 0.0))
        return replace(model, source_weights=weights, source_yield_stats=stats)

    def persist_model(self, model: LearningModel) -> None:
        """Persist learning_state to the campaign + yield stats to discovery_sources."""
        campaign = self._storage.campaigns.get(model.campaign_id)
        if campaign is not None:
            learning_state = dict(campaign.learning_state or {})
            learning_state.update(
                {
                    "converting_role_signature": model.converting_role_signature,
                    "converting_samples": model.converting_samples,
                    "exploration_budget": model.exploration_budget,
                    # #12: cap the feature_stats blob before it is written so the
                    # JSONB column does not grow without bound over 24/7 folds.
                    "feature_stats": cap_feature_stats(model.feature_stats),
                }
            )
            self._storage.campaigns.add(
                dataclasses.replace(campaign, learning_state=learning_state)
            )
        for key, weight in model.source_weights.items():
            ys = dict(model.source_yield_stats.get(key, {}))
            ys["weight"] = weight
            existing = self._storage.discovery_sources.get(model.campaign_id, key)
            self._storage.discovery_sources.upsert(
                DiscoverySource(
                    id=existing.id if existing else DiscoverySourceId(new_id()),
                    campaign_id=model.campaign_id,
                    source_key=key,
                    enabled=existing.enabled if existing else True,
                    yield_stats=ys,
                )
            )
        self._storage.commit()

    # --- source-yield learning (FR-DISC-5 / FR-LEARN-6) -------------------
    def record_source_yield(
        self, model: LearningModel, yields: dict[str, int]
    ) -> LearningModel:
        """Fold per-source match counts into decayed source weights (simple path)."""
        return self.record_source_funnel(
            model, {k: {"matches": v} for k, v in yields.items()}
        )

    def record_source_funnel(
        self, model: LearningModel, funnels: dict[str, dict]
    ) -> LearningModel:
        """Fold a per-source funnel (matches/approvals/submissions) into weights.

        Each source's decayed weight is its prior decayed weight plus this run's
        funnel score (matches + weighted approvals + weighted submissions). The full
        funnel is accumulated in ``source_yield_stats`` so the UI can show the real
        conversion path, not just a scalar (FR-DISC-5).
        """
        weights = dict(model.source_weights)
        stats = {k: dict(v) for k, v in model.source_yield_stats.items()}
        for key in set(weights) | set(funnels):
            funnel = funnels.get(key, {})
            matches = int(funnel.get("matches", 0))
            approvals = int(funnel.get("approvals", 0))
            submissions = int(funnel.get("submissions", 0))
            run_score = (
                matches * _W_MATCH + approvals * _W_APPROVAL + submissions * _W_SUBMISSION
            )
            prior = weights.get(key, 0.0)
            weights[key] = prior * _DECAY + run_score
            acc = stats.setdefault(key, {})
            acc["matches"] = int(acc.get("matches", 0)) + matches
            acc["approvals"] = int(acc.get("approvals", 0)) + approvals
            acc["submissions"] = int(acc.get("submissions", 0)) + submissions
        return replace(model, source_weights=weights, source_yield_stats=stats)

    def record_funnel_atomic(
        self, campaign_id: CampaignId, funnels: dict[str, dict]
    ) -> LearningModel:
        """Atomically load -> fold a funnel -> persist for a campaign.

        FR-LEARN-1/FR-DUR-2: the per-campaign lock serializes this read-modify-write
        with the approval/submission path (``record_source_event``) so concurrent
        match/approval/submission folds can't lose-update the shared learning state.
        """
        with _campaign_lock(campaign_id):
            model = self.load_model(campaign_id)
            model = self.record_source_funnel(model, funnels)
            self.persist_model(model)
        return model

    def record_source_event(
        self, campaign_id: CampaignId, source_key: str, leg: str, count: int = 1
    ) -> LearningModel:
        """Record ONE funnel leg (matches/approvals/submissions) for a source + persist.

        Wires the approvals + submissions legs of the FR-DISC-5 funnel into the live
        approval/submission paths (they were previously computed but never recorded
        beyond ``matches``). Returns the updated model. Unknown legs are ignored.
        """
        if leg not in ("matches", "approvals", "submissions") or not source_key:
            return self.load_model(campaign_id)
        return self.record_funnel_atomic(campaign_id, {source_key: {leg: int(count)}})

    def _conversion_score(self, model: LearningModel, key: str) -> float:
        """Conversion-weighted yield score for a source (FR-DISC-5).

        Ranks by *conversion*, not raw volume: a source's score is its weighted
        conversion RATE — (approvals*wa + submissions*ws) per match — so a
        high-volume zero-conversion source can never outrank a low-volume converting
        one. Sources with no recorded matches fall back to their decayed weight so
        cold/seen-but-empty sources still order sensibly. Exploration (separately)
        still probes zero-data sources.
        """
        stats = model.source_yield_stats.get(key, {})
        matches = int(stats.get("matches", 0))
        approvals = int(stats.get("approvals", 0))
        submissions = int(stats.get("submissions", 0))
        if matches <= 0:
            # No volume to normalize against — rank converting legs directly, else
            # fall back to the decayed weight (keeps cold sources ordered).
            converted = approvals * _W_APPROVAL + submissions * _W_SUBMISSION
            return converted or model.source_weights.get(key, 0.0)
        return (approvals * _W_APPROVAL + submissions * _W_SUBMISSION) / matches

    def build_summary(self, campaign_id: CampaignId) -> dict:
        """Plain-language, white-labeled read-model of what the system has learned.

        Built purely from the persisted ``LearningModel`` (no LLM, no secrets): the
        source ranking with each source's real funnel (matched -> approved ->
        submitted), the overall conversion totals across all sources, the roles that
        actually convert (titles only — never the raw embedding vector), and the
        exploration budget. Backs the operator-visibility (Insights) surface so the
        user can see and trust the bias the engine is applying.
        """
        model = self.load_model(campaign_id)
        ranked = self.source_ranking(model)
        sources: list[dict] = []
        total_matches = total_approvals = total_submissions = 0
        for key in ranked:
            ys = model.source_yield_stats.get(key, {})
            matches = int(ys.get("matches", 0))
            approvals = int(ys.get("approvals", 0))
            submissions = int(ys.get("submissions", 0))
            total_matches += matches
            total_approvals += approvals
            total_submissions += submissions
            sources.append(
                {
                    "source": key,
                    "matched": matches,
                    "approved": approvals,
                    "submitted": submissions,
                    # Conversion rate as a percentage (submissions per match) for a
                    # readable bar; ``None`` when there is no volume to normalize.
                    "conversion_rate": (
                        round(100.0 * submissions / matches, 1) if matches > 0 else None
                    ),
                }
            )
        return {
            "campaign_id": str(campaign_id),
            "summary": {
                "total_matched": total_matches,
                "total_approved": total_approvals,
                "total_submitted": total_submissions,
                "sources_seen": len(sources),
            },
            "sources": sources,
            "converting_roles": self.converting_titles(model),
            "converting_samples": int(model.converting_samples),
            # 0-1 explore/exploit knob (read-only here; editable on the Sources tab).
            "exploration_budget": float(model.exploration_budget),
        }

    def source_ranking(self, model: LearningModel) -> list[str]:
        """Sources ordered by learned conversion-weighted yield, highest first.

        FR-DISC-5: reweight toward conversion and down-weight low-yield sources, so
        raw match volume alone can't dominate the ranking.
        """
        keys = set(model.source_weights) | set(model.source_yield_stats)
        # Total, deterministic order: score DESC, then source name ASC so equal-yield
        # sources have a stable tie-break (set iteration order is otherwise unstable).
        return sorted(keys, key=lambda k: (-self._conversion_score(model, k), k))

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
        # FR-LEARN-6: a zero budget disables exploration entirely; only floor the
        # cap to 1 when there *is* a positive budget so exploration is never a no-op.
        if not all_sources or budget <= 0.0:
            max_explore = 0
        else:
            max_explore = max(1, int(round(len(all_sources) * budget)))
        explore = explore[:max_explore]
        # FR-DISC-5: every enabled source must land in exploit OR explore — cold /
        # unseen sources beyond the explore cap must not be silently dropped. Build
        # exploit from ranked order first, then any remaining enabled sources.
        ordered = ranked + [s for s in all_sources if s not in ranked]
        exploit = [s for s in ordered if s not in explore]
        return exploit, explore

    # --- converting-role signature (FR-LEARN-5) ---------------------------
    def record_converting_role(
        self, model: LearningModel, jd_text: str, *, title: str | None = None
    ) -> LearningModel:
        """Fold a converted role's JD into the running converting-role centroid.

        Cheap: an incremental mean over the local embedding vector. Discovery and
        scoring read ``converting_role_signature`` to bias toward roles that look like
        what actually converts (FR-LEARN-5). When a ``title`` is supplied it is also
        accumulated so discovery can bias its search titles toward the converting role.
        """
        if not jd_text.strip():
            return model
        vecs = self._embedding.embed([jd_text])
        if not vecs or not vecs[0]:
            # An empty/degenerate embedding can't be folded into the centroid;
            # leave the model unchanged rather than corrupt it / crash.
            return model
        vec = vecs[0]
        n = model.converting_samples
        prior = model.converting_role_signature.get("vector")
        if prior and len(prior) == len(vec):
            merged = [(prior[i] * n + vec[i]) / (n + 1) for i in range(len(vec))]
        else:
            merged = list(vec)
        sig = {"vector": merged}
        titles = list(model.converting_role_signature.get("titles", []))
        if title and title.strip() and title.strip() not in titles:
            titles.append(title.strip())
        if titles:
            sig["titles"] = titles
        return replace(model, converting_role_signature=sig, converting_samples=n + 1)

    def converting_titles(self, model: LearningModel) -> list[str]:
        """Titles of roles that actually converted, for discovery bias (FR-LEARN-5)."""
        return list(model.converting_role_signature.get("titles", []))

    # --- approve/decline taste bias (FR-LEARN-1/3, #237) ------------------
    def taste_bias(self, model: LearningModel, text: str) -> float:
        """Bounded multiplicative bias from accumulated approve/decline taste (#237).

        Reads the per-feature ``feature_stats`` the approve/decline fold accumulates
        (and that ``load_model``/``persist_model`` round-trip) and returns a small
        signed multiplier in ``[0.8, 1.2]`` for a posting's text: a value the user has
        consistently DECLINED nudges the score down, a consistently APPROVED one nudges
        it up. Returns exactly ``1.0`` when nothing in the posting matches the learned
        taste, so a cold campaign is byte-identical to before. This wires the previously
        write-only ``feature_stats`` into scoring so the feedback loop actually closes.
        """
        return taste_bias(model.feature_stats, text)

    def converting_alignment(self, model: LearningModel, jd_text: str) -> float:
        """Cosine-ish alignment in [0,1] of a JD to the converting-role signature.

        Returns 0.0 when no converting signature exists yet (no bias to apply).
        """
        sig = model.converting_role_signature.get("vector")
        if not sig or not jd_text.strip():
            return 0.0
        vecs = self._embedding.embed([jd_text])
        if not vecs or not vecs[0]:
            return 0.0
        vec = vecs[0]
        # Mismatched dimensions can't be compared meaningfully (mirrors the
        # length guard in record_converting_role): no bias rather than a crash.
        if len(sig) != len(vec):
            return 0.0
        dot = sum(a * b for a, b in zip(sig, vec, strict=False))
        na = sum(a * a for a in sig) ** 0.5
        nb = sum(b * b for b in vec) ** 0.5
        if na == 0.0 or nb == 0.0:
            return 0.0
        cos = dot / (na * nb)
        return max(0.0, min(1.0, (cos + 1.0) / 2.0))

    # --- attribute-cloud cross-referencing (FR-LEARN-3/4) -----------------
    def cross_reference_attributes(
        self, campaign_id: CampaignId, parsed: dict[str, str]
    ) -> CrossReferenceResult:
        """Fold parsed input (e.g. resume/chat/survey) into the attribute cloud.

        For each ``name -> value`` learned from an input (FR-LEARN-3 "every input"):

        - **non-integral**: auto-apply (add or update in place), keeping the cloud up to
          date without friction (FR-LEARN-4 auto-apply);
        - **integral**: NEVER auto-apply — record a pending change for the user to
          confirm via the shared confirmation gate (FR-FB-3 reuse).

        Returns what was applied vs. what awaits confirmation. Cheap + local: no LLM.
        """
        existing = {
            a.name.lower(): a
            for a in self._storage.attributes.list_for_campaign(campaign_id)
        }
        result = CrossReferenceResult()
        for name, value in parsed.items():
            value = (value or "").strip()
            if not value:
                continue
            prior = existing.get(name.lower())
            if prior is not None and prior.value == value:
                continue  # no change
            is_integral = bool(prior and prior.is_integral)
            is_sensitive = bool(prior and prior.is_sensitive)
            if is_sensitive:
                # Sensitive fields are never auto-learned (FR-ATTR-6); skip silently.
                continue
            if requires_confirmation(is_integral):
                result.pending.append(
                    {
                        "name": name,
                        "current_value": prior.value if prior else None,
                        "proposed_value": value,
                        "is_integral": True,
                        "reason": "integral attribute change requires confirmation (FR-FB-3)",
                    }
                )
                continue
            attr = Attribute(
                id=prior.id if prior else AttributeId(new_id()),
                campaign_id=campaign_id,
                name=prior.name if prior else name,
                value=value,
                aliases=prior.aliases if prior else (),
                is_integral=False,
                is_sensitive=False,
            )
            self._storage.attributes.add(attr)
            result.applied.append(attr)
        if result.applied:
            self._storage.commit()
        return result

    def ingest_decline_atomic(
        self,
        campaign_id: CampaignId,
        *,
        feedback_text: str,
        criteria_delta: dict | None = None,
    ) -> LearningModel:
        """Atomically load -> fold decline feedback -> persist for a campaign (CONC-4).

        FR-LEARN-1/FR-DUR-2: the per-campaign lock serializes this read-modify-write of
        the shared ``campaign.learning_state`` with the funnel path
        (``record_funnel_atomic``/``record_source_event``) so a concurrent source-event
        fold can't lose-update the decline feedback (or vice-versa).
        """
        with _campaign_lock(campaign_id):
            model = self.load_model(campaign_id)
            model = self.ingest_decline_feedback(
                model, feedback_text=feedback_text, criteria_delta=criteria_delta
            )
            self.persist_model(model)
        return model

    def fold_decision_atomic(
        self, campaign_id: CampaignId, *, approved: bool, features: dict | None = None
    ) -> LearningModel:
        """Atomically load -> fold an approve/decline decision -> persist (CONC-4).

        FR-LEARN-1/2/FR-DUR-2: the per-campaign lock serializes this read-modify-write
        of the shared ``campaign.learning_state`` with the funnel + decline folds so a
        concurrent record can't lose-update the per-feature taste signal. Used to fold
        the digest APPROVE branch's positive taste (FR-LEARN-2), redline-revision
        feedback (FR-LEARN-3), chat taste (FR-LEARN-3), and soft-error resolutions
        (FR-LEARN-4) without bypassing the shared lock.
        """
        if not features:
            return self.load_model(campaign_id)
        with _campaign_lock(campaign_id):
            model = self.load_model(campaign_id)
            model = self.record_decision(model, approved=approved, features=features)
            self.persist_model(model)
        return model

    def ingest_decline_feedback(
        self, model: LearningModel, *, feedback_text: str, criteria_delta: dict | None = None
    ) -> LearningModel:
        """Fold a decline's free-text + criteria delta into feature stats (FR-DIG-5).

        Cheap keyword folding so the next run's scoring leans away from declined
        signals; the structured ``criteria_delta`` is the authoritative bias.
        """
        features = dict(criteria_delta or {})
        for token in feedback_text.lower().split():
            if len(token) > 3:
                features.setdefault(f"feedback:{token}", token)
        return self.record_decision(model, approved=False, features=features)

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
        # #12: bound the blob at fold time so it never grows unbounded across decisions.
        return replace(model, feature_stats=cap_feature_stats(stats))

    # --- AWM workflow induction (#306 / Skyvern parity #351) ----------------
    def induce_workflow(self, routine_store, domain: str, steps):
        """Induce a reusable per-ATS routine from a successful pre-fill (#351, #306).

        Skyvern parity: after a successful pre-fill on a given ATS the engine learns a
        reusable *routine* (the compact op-sequence that worked, keyed by domain) so
        the next application to that ATS is guided by the induced routine rather than
        re-derived cold. This is the learning-side entry point that folds a working
        trace into the process-lived :class:`~applicant.ports.driven.routine_store.RoutineStore`
        (AWM workflow-induction), returning the stored :class:`Routine` (or ``None``
        when there is nothing to induce or no store is wired).

        The routine is **data, not free text** — fill/select/upload steps reference the
        attribute cloud / document library by id, never a literal value, so an induced
        routine can never smuggle a fabricated answer into a form (NFR-TRUTH-1).
        """
        if routine_store is None or not domain or not steps:
            return None
        return routine_store.induce(domain, tuple(steps))
