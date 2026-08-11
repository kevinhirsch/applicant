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
        self, storage, learning, *, criteria=None, advanced_learning=None, pending_actions=None, llm=None
    ) -> None:
        self._storage = storage
        self._learning = learning
        self._llm = llm
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

    def submit_posting_feedback(
        self, campaign_id, posting_id, *, sentiment: str, text: str
    ) -> dict:
        """Per-posting free-text +/- feedback, LLM-parsed into learning (FR-FB-2/LEARN-3).

        The LLM reads the posting + the user's words and extracts reusable preferences:
        ``likes`` (attributes to SEEK) fold as approve-signals, ``dislikes`` (to AVOID)
        as decline-signals, and any ``criteria_delta`` (titles/keywords/salary/work_mode)
        applies as a transparent learned adjustment. Degrades to sentiment-only keyword
        folding when no LLM is wired, so the loop never breaks.
        """
        posting = None
        try:
            posting = self._storage.postings.get(posting_id)
        except Exception:  # pragma: no cover - a missing posting still records sentiment
            posting = None
        parsed = self._parse_feedback_with_llm(posting, sentiment, text)
        likes = [str(x).strip() for x in (parsed.get("likes") or []) if str(x).strip()]
        dislikes = [str(x).strip() for x in (parsed.get("dislikes") or []) if str(x).strip()]
        raw_delta = parsed.get("criteria_delta") or {}
        allowed = ("titles", "keywords", "salary_floor", "work_modes", "locations")
        criteria_delta = {k: v for k, v in raw_delta.items() if k in allowed}
        model = self._learning.load_model(campaign_id)
        if likes:
            model = self._learning.record_decision(
                model, approved=True, features={f"like:{k}": k for k in likes}
            )
        if dislikes:
            model = self._learning.record_decision(
                model, approved=False, features={f"dislike:{k}": k for k in dislikes}
            )
        if not likes and not dislikes:
            # No structured parse (or no LLM): fall back to the overall sentiment.
            if str(sentiment).lower().startswith("pos"):
                feats = {f"like:{t}": t for t in text.lower().split() if len(t) > 3}
                model = self._learning.record_decision(model, approved=True, features=feats)
            else:
                model = self._learning.ingest_decline_feedback(model, feedback_text=text)
        self._learning.persist_model(model)
        if self._criteria is not None and criteria_delta:
            self._criteria.apply_learned_adjustment(
                campaign_id,
                adjustment=criteria_delta,
                rationale=f"posting feedback ({sentiment}): {text[:160]}",
            )
        return {
            "folded": True,
            "sentiment": sentiment,
            "likes": likes,
            "dislikes": dislikes,
            "criteria_delta": criteria_delta,
        }

    def _parse_feedback_with_llm(self, posting, sentiment: str, text: str) -> dict:
        """Turn free text about ONE posting into {likes, dislikes, criteria_delta}."""
        if self._llm is None:
            return {}
        import json
        import re

        from applicant.ports.driven.llm import ChatMessage

        try:
            from applicant.core.rules.prompt_injection import neutralize_untrusted_text
            safe = neutralize_untrusted_text(text)[:1000]
        except Exception:
            safe = (text or "")[:1000]
        title = (getattr(posting, "title", "") or "") if posting else ""
        company = (getattr(posting, "company", "") or "") if posting else ""
        desc = ((getattr(posting, "description", "") or "") if posting else "")[:1200]
        schema = {
            "type": "object",
            "properties": {
                "likes": {"type": "array", "items": {"type": "string"}},
                "dislikes": {"type": "array", "items": {"type": "string"}},
                "criteria_delta": {"type": "object"},
            },
            "required": ["likes", "dislikes"],
        }
        system = ChatMessage(
            role="system",
            content=(
                "You convert a job-seeker's free-text feedback about ONE job posting into "
                "structured, REUSABLE learning signals. 'likes' = concrete attributes to seek "
                "in future postings; 'dislikes' = attributes to avoid. Optionally 'criteria_delta' "
                "with any of: titles (list), keywords (list to add), salary_floor (int, annual USD), "
                "work_modes (list), locations (list). Only include what the feedback clearly implies; "
                "be terse. Respond with JSON only."
            ),
        )
        user = ChatMessage(
            role="user",
            content=f"POSTING: {title} at {company}\n{desc}\n\nFEEDBACK (overall: {sentiment}):\n{safe}",
        )
        try:
            result = self._llm.complete(
                [system, user], start_tier=1, json_schema=schema, max_tokens=320
            )
            data = getattr(result, "structured", None) or {}
            if not data and getattr(result, "text", ""):
                m = re.search(r"\{.*\}", result.text, re.S)
                data = json.loads(m.group(0)) if m else {}
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

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
