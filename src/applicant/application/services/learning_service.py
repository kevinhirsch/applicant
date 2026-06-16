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
from dataclasses import dataclass, field, replace

from applicant.core.entities.attribute import Attribute
from applicant.core.entities.discovery_source import DiscoverySource
from applicant.core.entities.learning_model import LearningModel
from applicant.core.ids import AttributeId, CampaignId, DiscoverySourceId, new_id
from applicant.core.rules.confirmation_gate import requires_confirmation


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
                    "feature_stats": model.feature_stats,
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

    # --- converting-role signature (FR-LEARN-5) ---------------------------
    def record_converting_role(self, model: LearningModel, jd_text: str) -> LearningModel:
        """Fold a converted role's JD into the running converting-role centroid.

        Cheap: an incremental mean over the local embedding vector. Discovery and
        scoring read ``converting_role_signature`` to bias toward roles that look like
        what actually converts (FR-LEARN-5).
        """
        if not jd_text.strip():
            return model
        vec = self._embedding.embed([jd_text])[0]
        n = model.converting_samples
        prior = model.converting_role_signature.get("vector")
        if prior and len(prior) == len(vec):
            merged = [(prior[i] * n + vec[i]) / (n + 1) for i in range(len(vec))]
        else:
            merged = list(vec)
        sig = {"vector": merged}
        return replace(model, converting_role_signature=sig, converting_samples=n + 1)

    def converting_alignment(self, model: LearningModel, jd_text: str) -> float:
        """Cosine-ish alignment in [0,1] of a JD to the converting-role signature.

        Returns 0.0 when no converting signature exists yet (no bias to apply).
        """
        sig = model.converting_role_signature.get("vector")
        if not sig or not jd_text.strip():
            return 0.0
        vec = self._embedding.embed([jd_text])[0]
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
        return replace(model, feature_stats=stats)
