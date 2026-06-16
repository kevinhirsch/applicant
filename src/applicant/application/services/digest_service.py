"""DigestService (FR-DIG-1..6, FR-FB-1).

# STAGE B — owned by Phase 1.

Builds the daily digest and records approve/decline-with-feedback decisions:

- one **row per viable role**: summary, link, work mode, viability score, and a
  human-readable **why-suggested** rationale (FR-DIG-3/4);
- an explicit **empty-day note** when nothing cleared the bar (FR-DIG-6) so silence is
  never ambiguous;
- **approve** / **decline-with-feedback** that record a ``Decision`` whose feedback +
  criteria-delta feed learning and the next run (FR-DIG-5, FR-FB-1).

The digest is channel-agnostic (email/web/Discord, FR-DIG-1/2): it returns plain rows;
the notification port delivers them.
"""

from __future__ import annotations

from applicant.core.entities.decision import Decision, DecisionType
from applicant.core.entities.search_criteria import SearchCriteria
from applicant.core.ids import ApplicationId, CampaignId, DecisionId, new_id

EMPTY_DAY_NOTE = "No new viable roles today — criteria unchanged, discovery still running (FR-DIG-6)."


class DigestService:
    def __init__(self, storage, notification, scoring=None) -> None:
        self._storage = storage
        self._notification = notification
        self._scoring = scoring

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
        return {
            "campaign_id": campaign_id,
            "rows": rows,
            "empty": not rows,
            "note": EMPTY_DAY_NOTE if not rows else None,
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
        return decision
