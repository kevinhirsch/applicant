"""PendingActionsQuery driving port (FR-UI-3).

Feeds the pending-actions portal: everything awaiting user input, each actionable.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from applicant.core.entities.pending_action import PendingAction
from applicant.core.ids import CampaignId


@runtime_checkable
class PendingActionsQueryPort(Protocol):
    """Inbound port for the pending-actions portal."""

    def list_pending(self, campaign_id: CampaignId) -> list[PendingAction]: ...
