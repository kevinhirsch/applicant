"""PendingActionsService (FR-UI-3).

The pending-actions portal is the 24/7 home base: a single, materialized surface
listing EVERYTHING awaiting the user across a campaign — digest approvals,
material/cover-letter/screening-answer reviews (placeholders until Phase 3), soft
errors (FR-ATTR-5), agent questions (FR-AGENT-4), and final-submit approvals
(Phase 2). Items are persisted to ``pending_actions`` so the portal survives
restarts, and each is actionable (resolve).

Kinds are stable strings the UI can switch on:
``digest_approval``, ``material_review``, ``missing_attr``, ``agent_question``,
``final_approval``, ``error``.
"""

from __future__ import annotations

from applicant.core.entities.pending_action import PendingAction
from applicant.core.ids import ApplicationId, CampaignId, PendingActionId, new_id

KIND_DIGEST_APPROVAL = "digest_approval"
KIND_MATERIAL_REVIEW = "material_review"
KIND_MISSING_ATTR = "missing_attr"
KIND_AGENT_QUESTION = "agent_question"
KIND_FINAL_APPROVAL = "final_approval"
KIND_ERROR = "error"


class PendingActionsService:
    def __init__(self, storage) -> None:
        self._storage = storage

    # --- materialize (FR-UI-3) --------------------------------------------
    def materialize(
        self,
        campaign_id: CampaignId,
        kind: str,
        title: str,
        *,
        application_id: ApplicationId | None = None,
        payload: dict | None = None,
        dedup_key: str | None = None,
    ) -> PendingAction:
        """Create (or reuse) a pending action. ``dedup_key`` avoids duplicates."""
        if dedup_key is not None:
            for existing in self._storage.pending_actions.list_open(campaign_id):
                if (existing.payload or {}).get("dedup_key") == dedup_key:
                    return existing
        merged_payload = dict(payload or {})
        if dedup_key is not None:
            merged_payload["dedup_key"] = dedup_key
        action = PendingAction(
            id=PendingActionId(new_id()),
            campaign_id=campaign_id,
            kind=kind,
            title=title,
            application_id=application_id,
            payload=merged_payload,
        )
        self._storage.pending_actions.add(action)
        self._storage.commit()
        return action

    # --- convenience constructors -----------------------------------------
    def digest_approval(
        self, campaign_id: CampaignId, application_id: ApplicationId, title: str, **payload
    ) -> PendingAction:
        return self.materialize(
            campaign_id,
            KIND_DIGEST_APPROVAL,
            title,
            application_id=application_id,
            payload=payload,
            dedup_key=f"digest_approval:{application_id}",
        )

    def missing_attribute(
        self, campaign_id: CampaignId, attribute_name: str, *, site_key: str = "", **payload
    ) -> PendingAction:
        """Soft error for a missing attribute during pre-fill (FR-ATTR-5)."""
        body = {"attribute_name": attribute_name, "site_key": site_key, **payload}
        return self.materialize(
            campaign_id,
            KIND_MISSING_ATTR,
            f"Missing detail needed: {attribute_name}",
            payload=body,
            dedup_key=f"missing_attr:{attribute_name}:{site_key}",
        )

    def agent_question(self, campaign_id: CampaignId, question: str, **payload) -> PendingAction:
        """Agent pause-and-ask item (FR-AGENT-4)."""
        return self.materialize(
            campaign_id, KIND_AGENT_QUESTION, question, payload=payload
        )

    # --- query + resolve (FR-UI-3) ----------------------------------------
    def list_pending(self, campaign_id: CampaignId) -> list[PendingAction]:
        return self._storage.pending_actions.list_open(campaign_id)

    def resolve(self, action_id: PendingActionId) -> None:
        self._storage.pending_actions.resolve(action_id)
        self._storage.commit()

    def resolve_by_dedup(self, campaign_id: CampaignId, dedup_key: str) -> None:
        """Resolve a materialized item by its dedup key (idempotency aid)."""
        for action in self._storage.pending_actions.list_open(campaign_id):
            if (action.payload or {}).get("dedup_key") == dedup_key:
                self._storage.pending_actions.resolve(action.id)
        self._storage.commit()
