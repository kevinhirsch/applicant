"""CriteriaService (FR-CRIT-1/2/3).

Per-campaign search criteria that are dynamic, human-readable, UI-editable at ALL times
(FR-CRIT-2), and mutable both **directly by the user** and **by the LLM** via
learning/feedback (FR-CRIT-3). Learned adjustments are surfaced transparently in
``learned_adjustments`` and are always user-overridable.

Criteria persist on ``campaigns.criteria`` (JSONB). Integral criteria changes route
through the shared confirmation gate (FR-FB-3) — the same gate the attribute cloud uses —
so a core criterion can never be silently mutated.

Token frugality (FR-LEARN-7, NFR-TOKEN-1): the LLM is used ONLY to produce a
human-readable summary of a learned delta; the structured criteria mutation itself is
deterministic. If no LLM is configured the summary degrades gracefully to a plain string.
"""

from __future__ import annotations

import dataclasses

from applicant.core.entities.search_criteria import SearchCriteria
from applicant.core.ids import CampaignId
from applicant.core.rules.confirmation_gate import ensure_change_allowed

#: Criteria fields treated as integral (changing them needs confirmation, FR-FB-3).
_INTEGRAL_FIELDS = frozenset({"titles", "locations", "salary_floor"})

_TUPLE_FIELDS = frozenset({"titles", "locations", "work_modes", "keywords"})


class CriteriaService:
    def __init__(self, storage, llm=None) -> None:
        self._storage = storage
        self._llm = llm

    # --- read (FR-CRIT-2 always-visible) ----------------------------------
    def get_criteria(self, campaign_id: CampaignId) -> SearchCriteria:
        campaign = self._storage.campaigns.get(campaign_id)
        if campaign is None:
            return SearchCriteria(campaign_id=campaign_id)
        return self._from_dict(campaign_id, dict(campaign.criteria or {}))

    # --- user edits (FR-CRIT-2/3 directly by the user) --------------------
    def edit_criteria(
        self,
        campaign_id: CampaignId,
        *,
        changes: dict,
        confirm: bool = False,
        clear_learned: bool = False,
    ) -> SearchCriteria:
        """Apply a direct user edit, gating integral changes (FR-CRIT-2/3, FR-FB-3).

        A user edit may also clear a learned adjustment (override, FR-CRIT-2).
        """
        current = self.get_criteria(campaign_id)
        is_integral = any(k in _INTEGRAL_FIELDS for k in changes)
        ensure_change_allowed(is_integral=is_integral, user_confirmed=confirm)
        updated = self._apply(current, changes)
        if clear_learned:
            updated = dataclasses.replace(updated, learned_adjustments={})
        self._persist(campaign_id, updated)
        return updated

    # --- LLM / learning mutation (FR-CRIT-3) ------------------------------
    def apply_learned_adjustment(
        self,
        campaign_id: CampaignId,
        *,
        adjustment: dict,
        rationale: str = "",
    ) -> SearchCriteria:
        """Mutate criteria from learning/feedback, surfaced transparently (FR-CRIT-3).

        Non-integral learned deltas auto-apply (FR-LEARN-4); the delta + a
        human-readable summary land in ``learned_adjustments`` so the user sees and can
        override it. Integral fields are NOT auto-applied here — they are recorded as a
        *proposed* learned adjustment for the user to confirm via ``edit_criteria``.
        """
        current = self.get_criteria(campaign_id)
        non_integral = {k: v for k, v in adjustment.items() if k not in _INTEGRAL_FIELDS}
        integral = {k: v for k, v in adjustment.items() if k in _INTEGRAL_FIELDS}
        updated = self._apply(current, non_integral)
        learned = dict(updated.learned_adjustments)
        learned["last_delta"] = adjustment
        learned["summary"] = self._summarize(adjustment, rationale)
        if integral:
            learned["proposed_integral"] = integral
        updated = dataclasses.replace(updated, learned_adjustments=learned)
        self._persist(campaign_id, updated)
        return updated

    # --- helpers ----------------------------------------------------------
    def _summarize(self, adjustment: dict, rationale: str) -> str:
        """Human-readable summary of a learned delta (LLM only here, FR-LEARN-7)."""
        fallback = "Learned criteria update: " + ", ".join(
            f"{k} -> {v}" for k, v in adjustment.items()
        )
        if rationale:
            fallback = f"{fallback} ({rationale})"
        if self._llm is None or not getattr(self._llm, "is_configured", lambda: False)():
            return fallback
        try:
            from applicant.ports.driven.llm import ChatMessage

            result = self._llm.complete(
                [
                    ChatMessage(
                        role="system",
                        content="Summarize this job-search criteria change in one plain sentence.",
                    ),
                    ChatMessage(role="user", content=f"{adjustment} because {rationale}"),
                ]
            )
            return result.text.strip() or fallback
        except Exception:
            return fallback

    def _apply(self, current: SearchCriteria, changes: dict) -> SearchCriteria:
        patch: dict = {}
        for key, value in changes.items():
            if key in _TUPLE_FIELDS:
                patch[key] = tuple(value)
            elif key in ("human_readable",):
                patch[key] = str(value)
            elif key == "salary_floor":
                patch[key] = int(value) if value is not None else None
        return dataclasses.replace(current, **patch)

    def _persist(self, campaign_id: CampaignId, criteria: SearchCriteria) -> None:
        campaign = self._storage.campaigns.get(campaign_id)
        if campaign is None:
            return
        self._storage.campaigns.add(
            dataclasses.replace(campaign, criteria=self._to_dict(criteria))
        )
        self._storage.commit()

    @staticmethod
    def _to_dict(c: SearchCriteria) -> dict:
        return {
            "human_readable": c.human_readable,
            "titles": list(c.titles),
            "locations": list(c.locations),
            "work_modes": list(c.work_modes),
            "salary_floor": c.salary_floor,
            "keywords": list(c.keywords),
            "learned_adjustments": c.learned_adjustments,
        }

    @staticmethod
    def _from_dict(campaign_id: CampaignId, d: dict) -> SearchCriteria:
        return SearchCriteria(
            campaign_id=campaign_id,
            human_readable=d.get("human_readable", ""),
            titles=tuple(d.get("titles", ())),
            locations=tuple(d.get("locations", ())),
            work_modes=tuple(d.get("work_modes", ())),
            salary_floor=d.get("salary_floor"),
            keywords=tuple(d.get("keywords", ())),
            learned_adjustments=dict(d.get("learned_adjustments", {})),
        )
