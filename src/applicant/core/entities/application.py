"""Application entity — the durable application record (FR-LOG-1, FR-DUR-1).

``status`` is the §7 state machine (``ApplicationState``). Transitions are
validated by ``applicant.core.state_machine``.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

from applicant.core.ids import (
    ApplicationId,
    CampaignId,
    JobPostingId,
    ResumeVariantId,
)
from applicant.core.state_machine import ApplicationState, transition


@dataclass(frozen=True)
class Application:
    """A single application moving through the §7 lifecycle."""

    id: ApplicationId
    campaign_id: CampaignId
    posting_id: JobPostingId
    status: ApplicationState = ApplicationState.DISCOVERED
    role_name: str | None = None
    job_title: str | None = None
    work_mode: str | None = None
    root_url: str | None = None
    resume_variant_id: ResumeVariantId | None = None
    sandbox_session_url: str | None = None
    attributes_used: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def with_status(self, to: ApplicationState) -> Application:
        """Return a copy advanced to ``to``, validating the transition (§7).

        Raises ``IllegalStateTransition`` for illegal moves.
        """
        new_state = transition(self.status, to)
        return replace(self, status=new_state)
