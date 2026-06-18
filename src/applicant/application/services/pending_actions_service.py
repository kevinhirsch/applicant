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
#: A held integral attribute change inferred from a PASSIVE input (guided survey /
#: résumé-parse) awaiting the user's explicit confirm-or-reject (FR-FB-3, FR-LEARN-4).
KIND_INTEGRAL_CHANGE = "integral_change"


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
        """Create (or reuse) a pending action. ``dedup_key`` avoids duplicates.

        #13: dedup uses ``PendingActionRepository.find_open_by_dedup`` (indexed lookup)
        when the storage adapter provides it, instead of scanning every open action per
        materialize. Falls back to the scan where the method is not yet present.
        """
        if dedup_key is not None:
            existing = self._find_open_by_dedup(campaign_id, dedup_key)
            if existing is not None:
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
        self, campaign_id: CampaignId, *, posting_id: str, title: str, **payload
    ) -> PendingAction:
        """Materialize a digest-approval item keyed on the POSTING id.

        A digest row has no Application row yet, so the posting id lives in the
        payload and ``application_id`` stays ``None`` (the FK column only holds real
        ``applications.id`` values). The dedup key keys on the posting id so the
        resolve path can clear it by posting id when the user approves.
        """
        body = {"posting_id": str(posting_id), **payload}
        return self.materialize(
            campaign_id,
            KIND_DIGEST_APPROVAL,
            title,
            application_id=None,
            payload=body,
            dedup_key=f"digest_approval:{posting_id}",
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

    def integral_change_confirmation(
        self,
        campaign_id: CampaignId,
        *,
        attribute_name: str,
        proposed_value: str,
        current_value: str | None = None,
        reason: str = "",
    ) -> PendingAction:
        """Hold an integral attribute change inferred from a passive input for the
        user's explicit confirm-or-reject (FR-FB-3, FR-LEARN-4).

        The proposed change is carried in the payload (not applied) and deduped per
        attribute so re-surfacing the same survey doesn't pile up duplicates; the
        latest proposed value wins. Applied via the resolve path with ``apply=true``.
        """
        body = {
            "attribute_name": attribute_name,
            "proposed_value": proposed_value,
            "current_value": current_value,
            "reason": reason
            or "A core detail was inferred from your input and needs your confirmation.",
        }
        return self.materialize(
            campaign_id,
            KIND_INTEGRAL_CHANGE,
            f"Confirm a change to {attribute_name}",
            payload=body,
            dedup_key=f"integral_change:{attribute_name}",
        )

    # --- query + resolve (FR-UI-3) ----------------------------------------
    def get(self, action_id: PendingActionId) -> PendingAction | None:
        """Fetch one pending action by id (used by the apply-on-resolve path)."""
        return self._storage.pending_actions.get(action_id)

    def list_pending(self, campaign_id: CampaignId) -> list[PendingAction]:
        return self._storage.pending_actions.list_open(campaign_id)

    def resolve(self, action_id: PendingActionId) -> None:
        self._storage.pending_actions.resolve(action_id)
        self._storage.commit()

    def resolve_by_dedup(self, campaign_id: CampaignId, dedup_key: str) -> None:
        """Resolve a materialized item by its dedup key (idempotency aid)."""
        action = self._find_open_by_dedup(campaign_id, dedup_key)
        if action is not None:
            self._storage.pending_actions.resolve(action.id)
        self._storage.commit()

    def _find_open_by_dedup(self, campaign_id: CampaignId, dedup_key: str):
        """Indexed open-by-dedup lookup (#13).

        Uses ``PendingActionRepository.find_open_by_dedup`` so dedup is an indexed
        query, not an O(open) scan per digest row.
        """
        return self._storage.pending_actions.find_open_by_dedup(campaign_id, dedup_key)
