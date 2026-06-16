"""AttributeEditing driving port (FR-ATTR-3, FR-FB-3).

Edit the attribute cloud. Integral changes route through the confirmation gate
(``core.rules.confirmation_gate``); non-integral may auto-apply.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from applicant.core.entities.attribute import Attribute
from applicant.core.ids import AttributeId, CampaignId


@runtime_checkable
class AttributeEditingPort(Protocol):
    """Inbound port for attribute-cloud editing."""

    def list_attributes(self, campaign_id: CampaignId) -> list[Attribute]: ...

    def upsert_attribute(self, attribute: Attribute, *, user_confirmed: bool = False) -> Attribute:
        """Add/update an attribute; integral changes require ``user_confirmed`` (FR-FB-3)."""
        ...

    def delete_attribute(self, attribute_id: AttributeId, *, user_confirmed: bool = False) -> None: ...
