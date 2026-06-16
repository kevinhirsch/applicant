"""FieldMapping entity (FR-ATTR-2).

Binds an attribute/alias to a specific application-form field for pre-fill. The
**mapping knowledge** (which ATS field a label fills) is learnable and shareable
across campaigns — a mapping with ``campaign_id is None`` is a global, shared
mapping — while the attribute *values* always stay per-campaign (FR-ATTR-2).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from applicant.core.ids import AttributeId, CampaignId, FieldMappingId


@dataclass(frozen=True)
class FieldMapping:
    """An attribute->form-field binding for a given ATS/site."""

    id: FieldMappingId
    site_key: str  # e.g. "workday", "greenhouse" — the ATS the field belongs to
    field_selector: str  # the detected form field (label/name/selector)
    # None -> a global, shared mapping (cross-campaign knowledge, FR-ATTR-2).
    campaign_id: CampaignId | None = None
    attribute_id: AttributeId | None = None
    metadata: dict = field(default_factory=dict)

    @property
    def is_shared(self) -> bool:
        """True when this mapping is global (not campaign-scoped) knowledge."""
        return self.campaign_id is None
