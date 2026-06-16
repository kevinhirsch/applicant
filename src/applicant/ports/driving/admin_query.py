"""AdminQuery driving port (FR-LOG-3, FR-OBS-2).

History/screenshots/workflow-state retrieval for the debug surface. Live in
Phase 4 (grayed until then).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from applicant.core.ids import ApplicationId, CampaignId


@runtime_checkable
class AdminQueryPort(Protocol):
    """Inbound port for observability/debug retrieval."""

    def application_history(self, campaign_id: CampaignId) -> list[dict]: ...
    def screenshots(self, application_id: ApplicationId) -> list[str]: ...
    def workflow_state(self, application_id: ApplicationId) -> dict: ...
