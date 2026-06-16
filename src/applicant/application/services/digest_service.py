"""DigestService (FR-DIG-1..6, FR-FB-1).

# STAGE B — owned by Phase 1.

Builds the daily digest, delivers it across channels, and records
approve/decline-with-feedback decisions that close the learning loop:

- one **row per viable role**: summary, link, work mode, viability score, and a
  human-readable **why-suggested** rationale (FR-DIG-3/4);
- an explicit **empty-day note** when nothing cleared the bar (FR-DIG-6) so silence is
  never ambiguous, plus what was searched and why;
- **delivery** = email payload + webpage payload + a Discord "ready" ping; the digest
  is EXEMPT from the Odysseus visual style — it has its own template (FR-DIG-2);
- **approve** / **decline-with-feedback** record a ``Decision`` whose feedback +
  criteria-delta round-trip into ``LearningService`` and the next run's criteria via
  ``CriteriaService`` (FR-DIG-5, FR-FB-1), and notify-idempotency expires the other
  channels (FR-NOTIF-3).
"""

from __future__ import annotations

from applicant.core.entities.decision import Decision, DecisionType
from applicant.core.entities.search_criteria import SearchCriteria
from applicant.core.ids import ApplicationId, CampaignId, DecisionId, new_id

EMPTY_DAY_NOTE = "No new viable roles today — criteria unchanged, discovery still running (FR-DIG-6)."


class DigestService:
    def __init__(
        self,
        storage,
        notification,
        scoring=None,
        *,
        learning=None,
        criteria=None,
        notification_service=None,
        pending_actions=None,
    ) -> None:
        self._storage = storage
        self._notification = notification
        self._scoring = scoring
        self._learning = learning
        self._criteria = criteria
        self._notification_service = notification_service
        self._pending = pending_actions

    # --- digest assembly (FR-DIG-3/4) -------------------------------------
    def build_digest(
        self, campaign_id: CampaignId, criteria: SearchCriteria | None = None
    ) -> list[dict]:
        """Assemble digest rows for every viable posting in the campaign."""
        postings = self._storage.postings.list_for_campaign(campaign_id)
        rows: list[dict] = []
        for posting in postings:
            row = {
                "posting_id": posting.id,
                "title": posting.title,
                "company": posting.company,
                "summary": f"{posting.title} at {posting.company}",
                "link": posting.source_url,
                "work_mode": posting.work_mode,
                "salary": posting.salary,
                "source": posting.source_key,
            }
            if self._scoring is not None:
                scoring = self._scoring.score_posting(posting, criteria)
                if not self._scoring.is_viable(scoring):
                    continue  # below threshold; excluded from the digest (FR-AGENT-3)
                row["viability_score"] = round(scoring.score * 100)
                row["why_suggested"] = scoring.rationale
            else:
                row["viability_score"] = None
                row["why_suggested"] = "scoring pending"
            rows.append(row)
        return rows

    def build_digest_payload(
        self, campaign_id: CampaignId, criteria: SearchCriteria | None = None
    ) -> dict:
        """Full digest payload incl. the empty-day note (FR-DIG-6)."""
        rows = self.build_digest(campaign_id, criteria)
        searched = self._searched_summary(campaign_id, criteria)
        return {
            "campaign_id": campaign_id,
            "rows": rows,
            "empty": not rows,
            "note": (
                f"{EMPTY_DAY_NOTE} Searched: {searched}." if not rows else None
            ),
            "searched": searched,
        }

    def _searched_summary(
        self, campaign_id: CampaignId, criteria: SearchCriteria | None
    ) -> str:
        """A short 'here's what I searched and why' line for the empty-day note."""
        sources = [
            s.source_key
            for s in self._storage.discovery_sources.list_for_campaign(campaign_id)
            if s.enabled
        ]
        titles = list(criteria.titles) if criteria else []
        bits = []
        if titles:
            bits.append("titles=" + ", ".join(titles))
        if sources:
            bits.append("sources=" + ", ".join(sorted(sources)))
        return "; ".join(bits) or "default criteria across the enabled sources"

    # --- delivery (FR-DIG-1/2) --------------------------------------------
    def render_email(self, campaign_id: CampaignId, criteria=None) -> dict:
        """Email payload — its OWN template, exempt from the Odysseus style (FR-DIG-2)."""
        payload = self.build_digest_payload(campaign_id, criteria)
        lines = ["<h1>Your daily digest</h1>"]
        if payload["empty"]:
            lines.append(f"<p><em>{payload['note']}</em></p>")
        else:
            lines.append(
                "<table border='1' cellpadding='6'><tr><th>Role</th><th>Work mode</th>"
                "<th>Score</th><th>Why suggested</th><th>Link</th></tr>"
            )
            for r in payload["rows"]:
                lines.append(
                    f"<tr><td>{r['summary']}</td><td>{r['work_mode'] or '-'}</td>"
                    f"<td>{r['viability_score']}</td><td>{r['why_suggested']}</td>"
                    f"<td><a href='{r['link']}'>open</a></td></tr>"
                )
            lines.append("</table>")
        return {
            "subject": "Your daily digest"
            if not payload["empty"]
            else "Daily digest — no new matches today",
            "html": "\n".join(lines),
            "campaign_id": campaign_id,
            "row_count": len(payload["rows"]),
        }

    def render_webpage(self, campaign_id: CampaignId, criteria=None) -> dict:
        """Webpage payload (rows + note) — own digest template (FR-DIG-2)."""
        return self.build_digest_payload(campaign_id, criteria)

    def deliver(self, campaign_id: CampaignId, criteria=None) -> dict:
        """Deliver the digest: build payloads + fire the Discord 'ready' ping (FR-DIG-2).

        Also materializes a digest-approval pending action per viable row so the
        portal lists them (FR-UI-3). Returns the assembled payloads + the notify
        handle so callers/tests can assert delivery.
        """
        payload = self.build_digest_payload(campaign_id, criteria)
        email = self.render_email(campaign_id, criteria)
        handle = None
        if self._notification_service is not None:
            handle = self._notification_service.notify_digest_ready(
                str(campaign_id), count=len(payload["rows"])
            )
        if self._pending is not None:
            for row in payload["rows"]:
                self._pending.digest_approval(
                    campaign_id,
                    ApplicationId(str(row["posting_id"])),
                    f"Review: {row['summary']}",
                    link=row["link"],
                    score=row["viability_score"],
                )
        return {
            "payload": payload,
            "email": email,
            "notify_handle": handle,
            "delivered_channels": (
                self._notification.configured_channels()
                if hasattr(self._notification, "configured_channels")
                else []
            ),
        }

    # --- decisions (FR-DIG-3/5, FR-FB-1) ----------------------------------
    def approve(self, application_id: ApplicationId) -> Decision:
        decision = Decision(
            id=DecisionId(new_id()),
            application_id=application_id,
            type=DecisionType.APPROVE,
        )
        self._storage.decisions.add(decision)
        self._storage.commit()
        self._close_loop(decision)
        return decision

    def decline(
        self,
        application_id: ApplicationId,
        feedback_text: str = "",
        criteria_delta: dict | None = None,
    ) -> Decision:
        """Record a decline carrying feedback + a criteria delta for learning."""
        decision = Decision(
            id=DecisionId(new_id()),
            application_id=application_id,
            type=DecisionType.DECLINE,
            feedback_text=feedback_text,
            criteria_delta=criteria_delta or {},
        )
        self._storage.decisions.add(decision)
        self._storage.commit()
        self._close_loop(decision)
        return decision

    # --- close the learning + criteria + idempotency loop -----------------
    def _close_loop(self, decision: Decision) -> None:
        # Idempotency: acting expires the other channels (FR-NOTIF-3).
        if self._notification_service is not None:
            self._notification_service.acted(str(decision.application_id))
        # Resolve the digest-approval pending item (FR-UI-3).
        if self._pending is not None:
            campaign_id = self._campaign_for_application(decision.application_id)
            if campaign_id is not None:
                self._pending.resolve_by_dedup(
                    campaign_id, f"digest_approval:{decision.application_id}"
                )
        if decision.type is DecisionType.DECLINE:
            self._learn_from_decline(decision)

    def _learn_from_decline(self, decision: Decision) -> None:
        campaign_id = self._campaign_for_application(decision.application_id)
        if campaign_id is None:
            return
        # Fold the feedback into the learning model (FR-DIG-5, FR-LEARN-3).
        if self._learning is not None:
            model = self._learning.load_model(campaign_id)
            model = self._learning.ingest_decline_feedback(
                model,
                feedback_text=decision.feedback_text,
                criteria_delta=decision.criteria_delta,
            )
            self._learning.persist_model(model)
        # Bias the NEXT run's criteria from the structured delta (FR-DIG-5, FR-CRIT-3).
        if self._criteria is not None and decision.criteria_delta:
            self._criteria.apply_learned_adjustment(
                campaign_id,
                adjustment=decision.criteria_delta,
                rationale=f"declined: {decision.feedback_text}" or "decline feedback",
            )

    def _campaign_for_application(self, application_id: ApplicationId) -> CampaignId | None:
        app = self._storage.applications.get(application_id)
        return app.campaign_id if app is not None else None
