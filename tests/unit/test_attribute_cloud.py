"""Attribute cloud CRUD + binding + dynamic add + missing-attr (FR-ATTR-1/2/4/5).

Confirmation gate (FR-FB-3) and sensitive-field policy (FR-ATTR-6) are exercised at
the API level in the BDD steps; here we cover the service mechanics and field-mapping
binding semantics (shared vs per-campaign).
"""

from __future__ import annotations

import pytest

from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.attribute_cloud_service import AttributeCloudService
from applicant.application.services.pending_actions_service import PendingActionsService
from applicant.core.errors import ConfirmationRequired, SensitiveFieldViolation
from applicant.core.ids import CampaignId, new_id


def _svc():
    storage = InMemoryStorage()
    pending = PendingActionsService(storage)
    return storage, AttributeCloudService(storage, pending_actions=pending), pending


def test_upsert_and_list_with_aliases():
    storage, svc, _ = _svc()
    cid = CampaignId(new_id())
    svc.upsert(cid, "Phone", "555-1234", aliases=("Telephone", "Mobile"))
    attrs = svc.list_attributes(cid)
    assert len(attrs) == 1
    assert attrs[0].matches("mobile")


def test_integral_change_requires_confirmation():
    storage, svc, _ = _svc()
    cid = CampaignId(new_id())
    svc.upsert(cid, "Full legal name", "Kevin Hirsch", is_integral=True, confirm=True)
    with pytest.raises(ConfirmationRequired):
        svc.upsert(cid, "Full legal name", "Someone Else", is_integral=True, confirm=False)
    # Confirmed integral change is allowed.
    attr = svc.upsert(cid, "Full legal name", "Someone Else", is_integral=True, confirm=True)
    assert attr.value == "Someone Else"


def test_ai_add_rejects_sensitive():
    storage, svc, _ = _svc()
    cid = CampaignId(new_id())
    with pytest.raises(ConfirmationRequired):
        svc.ai_add_attribute(cid, "Gender", "male")


def test_sensitive_value_never_ai_guessed():
    storage, svc, _ = _svc()
    cid = CampaignId(new_id())
    with pytest.raises(SensitiveFieldViolation):
        svc.upsert(cid, "Gender", "", is_sensitive=True, ai_suggested="male", confirm=True)


def test_field_mapping_shared_vs_campaign():
    # FR-ATTR-2: mapping knowledge can be shared; values stay per-campaign.
    storage, svc, _ = _svc()
    cid_a = CampaignId(new_id())
    cid_b = CampaignId(new_id())
    a = svc.upsert(cid_a, "Phone", "555-AAAA")
    svc.upsert(cid_b, "Phone", "555-BBBB")
    # A shared mapping binds by knowledge; each campaign keeps its own value.
    svc.bind_field("workday", "phoneNumber", attribute_id=a.id, shared=True)
    mapping = storage.field_mappings.find("workday", "phoneNumber")
    assert mapping.is_shared
    resolved_a = svc.resolve_attribute_for_field(cid_a, "workday", "phoneNumber")
    resolved_b = svc.resolve_attribute_for_field(cid_b, "workday", "phoneNumber")
    assert resolved_a.value == "555-AAAA"
    assert resolved_b.value == "555-BBBB"


def test_missing_attribute_soft_error_then_acquire():
    # FR-ATTR-5: missing attr -> soft error (pending action) -> acquire + reuse.
    storage, svc, pending = _svc()
    cid = CampaignId(new_id())
    err = svc.resolve_missing(cid, "Visa status", site_key="workday", field_selector="visa")
    assert err.pending_action_id
    items = pending.list_pending(cid)
    assert any(i.kind == "missing_attr" for i in items)
    # User supplies the detail; it is stored and the soft error resolves.
    svc.acquire_missing(cid, "Visa status", "Citizen")
    assert svc.get_by_name(cid, "Visa status").value == "Citizen"
    assert not any(i.kind == "missing_attr" for i in pending.list_pending(cid))
