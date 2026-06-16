"""AttributeCloudService (FR-ATTR-1/2/3/4/5).

The per-campaign attribute cloud — dynamic attributes -> values with aliases
(FR-ATTR-1) — with full CRUD through the core rule gates:

- **confirmation gate** (FR-FB-3): integral changes require explicit confirmation;
- **sensitive-field policy** (FR-ATTR-6): EEO values come only from explicit answers,
  never AI-guessed (already enforced in the core);
- **field-mapping binding** (FR-ATTR-2): an attribute/alias binds to a specific ATS
  form field; the *mapping knowledge* is learnable + shareable across campaigns
  (``field_mappings`` with ``campaign_id is None``) while the *values* stay
  per-campaign;
- **dynamic add** (FR-ATTR-4): the AI/learning path may add attributes as
  applications require (non-sensitive auto-apply, integral confirm);
- **missing-attribute soft error** (FR-ATTR-5): ``resolve_missing`` raises a soft
  error to the user (a pending action), and once acquired the detail is stored and
  reused per campaign — the flow Phase 2 pre-fill will call.
"""

from __future__ import annotations

from dataclasses import dataclass

from applicant.core.entities.attribute import Attribute
from applicant.core.entities.field_mapping import FieldMapping
from applicant.core.errors import ConfirmationRequired
from applicant.core.ids import AttributeId, CampaignId, FieldMappingId, new_id
from applicant.core.rules import sensitive_fields
from applicant.core.rules.confirmation_gate import ensure_change_allowed


@dataclass(frozen=True)
class MissingAttributeError:
    """A soft error surfaced when a required attribute is absent (FR-ATTR-5)."""

    campaign_id: CampaignId
    attribute_name: str
    site_key: str
    field_selector: str
    pending_action_id: str | None = None


class AttributeCloudService:
    def __init__(self, storage, *, pending_actions=None) -> None:
        self._storage = storage
        self._pending = pending_actions

    # --- CRUD (FR-ATTR-1/3) -----------------------------------------------
    def list_attributes(self, campaign_id: CampaignId) -> list[Attribute]:
        return self._storage.attributes.list_for_campaign(campaign_id)

    def get_by_name(self, campaign_id: CampaignId, name: str) -> Attribute | None:
        for a in self._storage.attributes.list_for_campaign(campaign_id):
            if a.matches(name):
                return a
        return None

    def upsert(
        self,
        campaign_id: CampaignId,
        name: str,
        value: str,
        *,
        aliases: tuple[str, ...] = (),
        is_integral: bool = False,
        is_sensitive: bool = False,
        confirm: bool = False,
        ai_suggested: str | None = None,
    ) -> Attribute:
        """Add/update an attribute through the confirmation + sensitive gates.

        Raises ``ConfirmationRequired`` for an unconfirmed integral value change and
        ``SensitiveFieldViolation`` for an AI-guessed sensitive value.
        """
        prior = self.get_by_name(campaign_id, name)
        is_integral_change = is_integral or (prior is not None and prior.is_integral)
        is_value_change = prior is None or prior.value != value
        if is_value_change:
            ensure_change_allowed(
                is_integral=is_integral_change, user_confirmed=confirm
            )

        sensitive = is_sensitive or sensitive_fields.is_sensitive_field(name)
        decision = sensitive_fields.decide_sensitive_fill(
            name if sensitive else "non-sensitive", value, ai_suggested=ai_suggested
        )

        attr = Attribute(
            id=prior.id if prior else AttributeId(new_id()),
            campaign_id=campaign_id,
            name=prior.name if prior else name,
            value=decision.value if sensitive else value,
            aliases=tuple(aliases) or (prior.aliases if prior else ()),
            is_integral=is_integral_change,
            is_sensitive=sensitive,
        )
        self._storage.attributes.add(attr)
        self._storage.commit()
        return attr

    def delete(self, campaign_id: CampaignId, attribute_id: AttributeId) -> None:
        # In-memory + SqlAlchemy both expose add/get; delete via repo if present,
        # else mark by re-adding with empty value is not desired — use repo delete.
        repo = self._storage.attributes
        delete = getattr(repo, "delete", None)
        if delete is not None:
            delete(attribute_id)
            self._storage.commit()

    # --- field-mapping binding (FR-ATTR-2) --------------------------------
    def bind_field(
        self,
        site_key: str,
        field_selector: str,
        *,
        attribute_id: AttributeId | None = None,
        campaign_id: CampaignId | None = None,
        shared: bool = False,
        metadata: dict | None = None,
    ) -> FieldMapping:
        """Bind an attribute to an ATS form field (FR-ATTR-2).

        ``shared=True`` (or ``campaign_id=None``) records GLOBAL mapping knowledge
        reusable across campaigns; values always stay per-campaign on the attribute.
        """
        existing = self._storage.field_mappings.find(site_key, field_selector)
        mapping = FieldMapping(
            id=existing.id if existing else FieldMappingId(new_id()),
            site_key=site_key,
            field_selector=field_selector,
            campaign_id=None if shared else campaign_id,
            attribute_id=attribute_id,
            metadata=metadata or {},
        )
        self._storage.field_mappings.add(mapping)
        self._storage.commit()
        return mapping

    def resolve_attribute_for_field(
        self, campaign_id: CampaignId, site_key: str, field_selector: str
    ) -> Attribute | None:
        """Resolve an ATS field to a per-campaign attribute value (FR-ATTR-2).

        Looks up the (shared or campaign) mapping then reads the campaign-scoped
        attribute value. Returns ``None`` when no mapping/attribute exists.
        """
        mapping = self._storage.field_mappings.find(site_key, field_selector)
        if mapping is None or mapping.attribute_id is None:
            return None
        attr = self._storage.attributes.get(mapping.attribute_id)
        if attr is not None and attr.campaign_id == campaign_id:
            return attr
        # The mapping is shared knowledge; resolve the same NAME per campaign.
        if attr is not None:
            return self.get_by_name(campaign_id, attr.name)
        return None

    # --- dynamic add (FR-ATTR-4) ------------------------------------------
    def ai_add_attribute(
        self, campaign_id: CampaignId, name: str, value: str, *, confirm: bool = False
    ) -> Attribute:
        """AI/learning may add a NON-sensitive attribute as applications require.

        Sensitive fields are never AI-added (the core would reject a guess); integral
        adds still require confirmation (FR-FB-3).
        """
        if sensitive_fields.is_sensitive_field(name):
            raise ConfirmationRequired(
                f"Cannot AI-add sensitive attribute {name!r}; needs an explicit answer (FR-ATTR-6)."
            )
        return self.upsert(campaign_id, name, value, confirm=confirm)

    # --- missing-attribute soft error (FR-ATTR-5) -------------------------
    def resolve_missing(
        self, campaign_id: CampaignId, attribute_name: str, *, site_key: str = "", field_selector: str = ""
    ) -> MissingAttributeError:
        """Surface a soft error for a missing attribute during pre-fill (FR-ATTR-5).

        Phase 2 pre-fill calls this when a required field has no stored value. It
        materializes a pending action so the user can supply the detail; once they
        do (via ``upsert``), the value is stored and reused per campaign.
        """
        action_id = None
        if self._pending is not None:
            action = self._pending.missing_attribute(
                campaign_id, attribute_name, site_key=site_key, field_selector=field_selector
            )
            action_id = str(action.id)
        return MissingAttributeError(
            campaign_id=campaign_id,
            attribute_name=attribute_name,
            site_key=site_key,
            field_selector=field_selector,
            pending_action_id=action_id,
        )

    def acquire_missing(
        self, campaign_id: CampaignId, attribute_name: str, value: str, *, confirm: bool = False
    ) -> Attribute:
        """Store a detail the user supplied for a missing attribute (FR-ATTR-5)."""
        attr = self.upsert(campaign_id, attribute_name, value, confirm=confirm)
        if self._pending is not None:
            # Resolve any open missing-attr soft error for this attribute name,
            # regardless of which site/field surfaced it (FR-ATTR-5).
            prefix = f"missing_attr:{attribute_name}:"
            for action in self._pending.list_pending(campaign_id):
                if str(action.payload.get("dedup_key", "")).startswith(prefix):
                    self._pending.resolve(action.id)
        return attr
