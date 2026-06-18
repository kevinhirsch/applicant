"""FeedbackService (FR-FB-1/2/3).

Feedback flows into per-campaign learning from three sources (FR-FB-2):

- **decline-with-feedback** (FR-FB-1) — mandatory free text on a digest decline; the
  DigestService owns the decision record, this service folds the text into learning;
- **free-text / chat** at any time — a plain message that becomes feature signals;
- **guided survey** — structured question -> answer pairs.

Cross-referenced attribute updates honor the **confirmation gate** (FR-FB-3): a
parsed integral change is recorded as *pending* (the user confirms), while
non-integral changes auto-apply — this reuses ``LearningService.cross_reference_attributes``
so there is one code path for "every input" (FR-LEARN-3/4).
"""

from __future__ import annotations

from applicant.core.ids import CampaignId


class FeedbackService:
    def __init__(
        self, storage, learning, *, criteria=None, advanced_learning=None, pending_actions=None
    ) -> None:
        self._storage = storage
        self._learning = learning
        self._criteria = criteria
        # Optional AdvancedLearningService so a batch of parsed/observed inputs can be
        # continuously reconciled into the attribute cloud (FR-LEARN-4): auto-apply
        # non-integral, hold integral for confirmation, surface conflicts, skip
        # sensitive (EEO). Onboarding keeps its own reconciliation as-is.
        self._advanced_learning = advanced_learning
        # Optional PendingActionsService: when a PASSIVE input (survey / résumé-parse)
        # produces a held integral change, materialize it into the portal so the user
        # can confirm or reject it — otherwise the held change is never confirmable
        # (FR-FB-3, FR-LEARN-4).
        self._pending_actions = pending_actions

    def _materialize_pending(self, campaign_id: CampaignId, pending: list[dict]) -> None:
        """Surface held integral changes as confirm-or-reject portal items (FR-FB-3)."""
        if not self._pending_actions or not pending:
            return
        for change in pending:
            name = change.get("name")
            if not name:
                continue
            try:
                self._pending_actions.integral_change_confirmation(
                    campaign_id,
                    attribute_name=name,
                    proposed_value=str(change.get("proposed_value", "")),
                    current_value=change.get("current_value"),
                    reason=str(change.get("reason", "")),
                )
            except Exception:  # pragma: no cover - never break the feedback fold
                continue

    def submit_freetext(
        self, campaign_id: CampaignId, text: str, *, criteria_delta: dict | None = None
    ) -> dict:
        """Fold free-text/chat feedback into learning (FR-FB-2, FR-LEARN-3)."""
        model = self._learning.load_model(campaign_id)
        model = self._learning.ingest_decline_feedback(
            model, feedback_text=text, criteria_delta=criteria_delta
        )
        self._learning.persist_model(model)
        if self._criteria is not None and criteria_delta:
            self._criteria.apply_learned_adjustment(
                campaign_id, adjustment=criteria_delta, rationale=f"feedback: {text}"
            )
        return {"folded": True, "text": text}

    def submit_survey(self, campaign_id: CampaignId, answers: dict[str, str]) -> dict:
        """Fold a guided survey (question->answer) into learning (FR-FB-2).

        Survey answers also cross-reference the attribute cloud, honoring the
        confirmation gate for integral changes (FR-FB-3, FR-LEARN-4).
        """
        model = self._learning.load_model(campaign_id)
        features = {f"survey:{k}": v for k, v in answers.items() if v}
        model = self._learning.record_decision(model, approved=True, features=features)
        self._learning.persist_model(model)
        xref = self._learning.cross_reference_attributes(campaign_id, answers)
        # Held integral changes surface in the portal for confirm-or-reject (FR-FB-3).
        self._materialize_pending(campaign_id, xref.pending)
        return {
            "applied": [a.name for a in xref.applied],
            "pending": xref.pending,  # integral changes awaiting confirmation (FR-FB-3)
        }

    def ingest_parsed_input(self, campaign_id: CampaignId, parsed) -> dict:
        """Cross-reference any parsed input with the attribute cloud (FR-LEARN-3/4).

        Accepts either a ``{name: value}`` mapping (the simple path) or a list of
        observation dicts ``{"name","value","source"?,"is_integral"?}``. A list is
        routed through ``AdvancedLearningService.reconcile_inputs`` (FR-LEARN-4): it
        auto-applies non-integral non-conflicting values, holds integral ones for the
        confirmation gate, surfaces conflicts, and skips sensitive (EEO) values. The
        mapping form keeps the prior cheap cross-reference path.

        Non-integral auto-applies; integral is returned pending for confirmation.
        """
        if isinstance(parsed, list) and self._advanced_learning is not None:
            return self._reconcile_observations(campaign_id, parsed)
        xref = self._learning.cross_reference_attributes(campaign_id, parsed)
        self._materialize_pending(campaign_id, xref.pending)
        return {
            "applied": [a.name for a in xref.applied],
            "pending": xref.pending,
        }

    def _reconcile_observations(
        self, campaign_id: CampaignId, observations: list[dict]
    ) -> dict:
        """Reconcile a batch of observed inputs into the cloud (FR-LEARN-4)."""
        from applicant.core.entities.attribute import AttributeStore

        existing = tuple(self._storage.attributes.list_for_campaign(campaign_id))
        store = AttributeStore(campaign_id=campaign_id, attributes=existing)
        new_store, result = self._advanced_learning.reconcile_inputs(store, observations)
        # Persist only the auto-applied (non-integral, non-conflicting) attributes;
        # integral changes + conflicts are surfaced (never silently committed, FR-FB-3).
        applied_names = {p.name for p in result.applied}
        if applied_names:
            for attr in new_store.attributes:
                if attr.name in applied_names:
                    self._storage.attributes.add(attr)
            self._storage.commit()
        pending = [
            {
                "name": p.name,
                "current_value": p.current_value,
                "proposed_value": p.value,
                "is_integral": p.is_integral,
            }
            for p in result.pending
        ]
        # Held integral changes surface in the portal for confirm-or-reject (FR-FB-3).
        self._materialize_pending(campaign_id, pending)
        return {
            "applied": [p.name for p in result.applied],
            "pending": pending,
            "conflicts": [
                {
                    "name": p.name,
                    "current_value": p.current_value,
                    "proposed_value": p.value,
                    "is_integral": p.is_integral,
                }
                for p in result.conflicts
            ],
            "skipped": list(result.skipped),
        }
