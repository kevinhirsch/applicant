"""Attribute and AttributeStore entities (FR-ATTR-*).

``is_integral`` drives the confirmation gate (FR-FB-3); ``is_sensitive`` enforces
the EEO policy (FR-ATTR-6). The store is the per-campaign attribute->value cloud.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from applicant.core.ids import AttributeId, CampaignId


@dataclass(frozen=True)
class Attribute:
    """A single attribute->value mapping with aliases."""

    id: AttributeId
    campaign_id: CampaignId
    name: str
    value: str
    aliases: tuple[str, ...] = ()
    is_integral: bool = False  # FR-FB-3 confirmation gate
    is_sensitive: bool = False  # FR-ATTR-6 EEO policy

    def matches(self, label: str) -> bool:
        """True if ``label`` matches this attribute's name or any alias (ci)."""
        low = label.strip().lower()
        return low == self.name.lower() or low in {a.lower() for a in self.aliases}


@dataclass(frozen=True)
class AttributeStore:
    """Per-campaign attribute cloud (FR-ATTR-1).

    Pure container; the confirmation gate is enforced by callers via
    ``core.rules.confirmation_gate`` before mutating integral attributes.
    """

    campaign_id: CampaignId
    attributes: tuple[Attribute, ...] = field(default_factory=tuple)

    def find(self, label: str) -> Attribute | None:
        """Resolve a form-field label to an attribute by name/alias."""
        for attr in self.attributes:
            if attr.matches(label):
                return attr
        return None

    def upsert(self, attribute: Attribute) -> AttributeStore:
        """Return a new store with ``attribute`` added or replaced (by id)."""
        others = tuple(a for a in self.attributes if a.id != attribute.id)
        return replace(self, attributes=others + (attribute,))
