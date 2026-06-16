"""DiscoverySource entity — persisted per-campaign source toggle + yield (FR-DISC-2/5)."""

from __future__ import annotations

from dataclasses import dataclass, field

from applicant.core.ids import CampaignId, DiscoverySourceId


@dataclass(frozen=True)
class DiscoverySource:
    """A user-selectable discovery source, persisted per campaign.

    ``enabled`` is the user toggle (FR-DISC-2); ``yield_stats`` carries the learned
    source-yield record (matches -> approvals -> submissions, decayed weight) so
    ``LearningService`` can reweight future runs (FR-DISC-5, FR-LEARN-6).
    """

    id: DiscoverySourceId
    campaign_id: CampaignId
    source_key: str
    enabled: bool = True
    yield_stats: dict = field(default_factory=dict)
