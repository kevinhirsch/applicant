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


def test_resume_after_missing_attr_resumes_prefill_and_reuses_value():
    # FR-ATTR-5 end-to-end: missing attr blocks pre-fill -> user resolves ->
    # the pre-fill RESUMES using the stored value -> the value is reused next time
    # without re-asking. Proves resume_after_missing_attr is wired (it had no caller).
    from applicant.adapters.browser.patchright_browser import PatchrightBrowser
    from applicant.adapters.detection.detection_monitor import DetectionMonitor
    from applicant.adapters.sandbox.local_sandbox import LocalSandbox
    from applicant.application.services.prefill_service import PrefillService
    from applicant.core.entities.application import Application
    from applicant.core.entities.attribute import Attribute
    from applicant.core.ids import (
        ApplicationId,
        AttributeId,
        JobPostingId,
    )
    from applicant.core.state_machine import ApplicationState

    storage = InMemoryStorage()
    pending = PendingActionsService(storage)
    prefill = PrefillService(
        storage=storage,
        browser=PatchrightBrowser(),
        detection=DetectionMonitor(),
        sandbox=LocalSandbox(),
        credentials=None,
    )
    svc = AttributeCloudService(storage, pending_actions=pending, prefill=prefill)
    cid = CampaignId(new_id())

    def _attr(name, value, sensitive=False):
        return Attribute(
            id=AttributeId(new_id()), campaign_id=cid, name=name, value=value,
            is_sensitive=sensitive,
        )

    # Full answers EXCEPT Phone (the missing required attribute).
    answers = [
        _attr("Email Address", "kevin@kevinhirsch.com"),
        _attr("Password", "S3cretP@ss"),
        _attr("Verify Password", "S3cretP@ss"),
        _attr("First Name", "Kevin"),
        _attr("Last Name", "Hirsch"),
        _attr("Address", "1 Main St"),
        _attr("Current Job Title", "Engineer"),
        _attr("Years of Experience", "8"),
        _attr("Are you authorized to work?", "Yes"),
        _attr("Are you willing to relocate?", "Yes"),
        _attr("Gender", "Female", sensitive=True),
    ]
    for a in answers:
        storage.attributes.add(a)
    storage.commit()

    url = "https://acme.myworkdayjobs.com/job/123"
    app = Application(
        id=ApplicationId(new_id()), campaign_id=cid,
        posting_id=JobPostingId(new_id()),
        status=ApplicationState.APPROVED, root_url=url,
    )
    # Reach the account page + resume past it; the personal page needs Phone -> blocks.
    prefill.prefill_application(app, url, answers)
    resumed = (
        app.with_status(ApplicationState.SANDBOX_PROVISIONING)
        .with_status(ApplicationState.ACCOUNT_PREFILL)
        .with_status(ApplicationState.AWAITING_ACCOUNT_HUMAN_STEP)
    )
    blocked = prefill.resume_after_account(resumed, answers)
    assert blocked.state is ApplicationState.BLOCKED_MISSING_ATTR
    assert blocked.missing_attribute == "Phone"
    # Persist the blocked app so resume_after_missing_attr can find it.
    storage.applications.add(storage.applications.get(app.id) or app)
    storage.commit()

    # User resolves the missing attribute -> stored + pre-fill RESUMES using it.
    summary = svc.resume_after_missing_attr(cid, "Phone", "555-0100")
    assert summary["attribute"]["value"] == "555-0100"
    assert summary["resumed"], "the stalled application resumed"
    landed = summary["resumed"][0]["state"]
    assert landed == ApplicationState.AWAITING_FINAL_APPROVAL.value
    # The value is stored + reused (no re-ask): a brand-new application now fills the
    # Phone field straight through to final approval, never re-asking for it.
    assert svc.get_by_name(cid, "Phone").value == "555-0100"
    prefill2 = PrefillService(
        storage=storage,
        browser=PatchrightBrowser(),
        detection=DetectionMonitor(),
        sandbox=LocalSandbox(),
        credentials=None,
    )
    app2 = Application(
        id=ApplicationId(new_id()), campaign_id=cid,
        posting_id=JobPostingId(new_id()),
        status=ApplicationState.APPROVED, root_url=url,
    )
    attrs_now = storage.attributes.list_for_campaign(cid)
    prefill2.prefill_application(app2, url, attrs_now)
    resumed2 = (
        app2.with_status(ApplicationState.SANDBOX_PROVISIONING)
        .with_status(ApplicationState.ACCOUNT_PREFILL)
        .with_status(ApplicationState.AWAITING_ACCOUNT_HUMAN_STEP)
    )
    reused = prefill2.resume_after_account(resumed2, attrs_now)
    assert reused.state is ApplicationState.AWAITING_FINAL_APPROVAL  # no re-ask
