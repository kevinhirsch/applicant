"""OnboardingService tests (FR-ONBOARD-1/2/3, FR-ATTR-1/3/4/6, FR-FB-3)."""

from __future__ import annotations

import pytest

from applicant.adapters.resume_parser.resume_parser import ResumeParser
from applicant.adapters.storage.app_config_store import InMemoryAppConfigStore
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.onboarding_service import OnboardingService
from applicant.core.entities.campaign import Campaign
from applicant.core.ids import CampaignId
from applicant.core.rules.sensitive_fields import DECLINE_TO_SELF_IDENTIFY
from applicant.ports.driving.onboarding import REQUIRED_SECTIONS, IntakeSection

CID = "camp-1"

_RESUME = """\
Jane Q Candidate
jane@example.com | +1 (415) 555-0199

Experience:
Senior Engineer at Acme Corp    Jan 2020 - Present

Education:
B.S. Computer Science, State University    2013 - 2017

Skills:
Python, SQL, FastAPI
"""


@pytest.fixture
def svc_and_storage():
    storage = InMemoryStorage()
    storage.campaigns.add(Campaign(id=CampaignId(CID), name="c"))
    store = InMemoryAppConfigStore()
    svc = OnboardingService(storage=storage, config_store=store, resume_parser=ResumeParser())
    return svc, storage, store


def _fill_required(svc):
    for section in REQUIRED_SECTIONS:
        svc.save_section(CID, section, {"x": "value"})


def test_initial_state_incomplete(svc_and_storage):
    svc, *_ = svc_and_storage
    state = svc.get_state(CID)
    assert state.complete is False
    assert set(state.missing_sections) == {s.value for s in REQUIRED_SECTIONS}


def test_state_resumes_across_instances(svc_and_storage):
    svc, storage, store = svc_and_storage
    svc.save_section(CID, IntakeSection.IDENTITY, {"full_name": "Jane"})
    # New service over same store = restart (FR-ONBOARD-2).
    svc2 = OnboardingService(storage=storage, config_store=store, resume_parser=ResumeParser())
    state = svc2.get_state(CID)
    assert IntakeSection.IDENTITY.value in state.sections_complete
    assert state.intake[IntakeSection.IDENTITY.value]["full_name"] == "Jane"


def test_complete_gated_on_required_sections(svc_and_storage):
    svc, *_ = svc_and_storage
    state = svc.complete(CID)
    assert state.complete is False  # nothing filled yet
    _fill_required(svc)
    state = svc.complete(CID)
    assert state.complete is True
    assert svc.is_complete(CID) is True


def test_editing_reopens_completion(svc_and_storage):
    svc, *_ = svc_and_storage
    _fill_required(svc)
    assert svc.complete(CID).complete is True
    svc.save_section(CID, IntakeSection.COMPENSATION, {"salary_floor": "120000"})
    assert svc.is_complete(CID) is False  # re-confirmation required


def test_eeo_defaults_to_decline_and_is_sensitive(svc_and_storage):
    svc, storage, _ = svc_and_storage
    svc.save_section(CID, IntakeSection.EEO, {})  # user provides nothing
    state = svc.get_state(CID)
    eeo = state.intake[IntakeSection.EEO.value]
    assert eeo["gender"] == DECLINE_TO_SELF_IDENTIFY
    assert eeo["race_ethnicity"] == DECLINE_TO_SELF_IDENTIFY
    # Stored as sensitive attributes (FR-ATTR-6).
    attrs = storage.attributes.list_for_campaign(CampaignId(CID))
    gender = next(a for a in attrs if a.name == "gender")
    assert gender.is_sensitive is True
    assert gender.value == DECLINE_TO_SELF_IDENTIFY


def test_ingest_resume_bootstraps_attribute_cloud(svc_and_storage, tmp_path):
    svc, storage, _ = svc_and_storage
    p = tmp_path / "resume.txt"
    p.write_text(_RESUME, encoding="utf-8")
    result = svc.ingest_base_resume(CID, str(p))
    assert result.attribute_count > 0
    attrs = {a.name for a in storage.attributes.list_for_campaign(CampaignId(CID))}
    assert any(n.startswith("skill:") for n in attrs)
    assert any(n.startswith("work_history:") for n in attrs)
    assert "full_name" in attrs


def test_ingest_resume_integral_conflict_requires_confirmation(svc_and_storage, tmp_path):
    svc, storage, _ = svc_and_storage
    # Interview answer disagrees with the parsed resume on an INTEGRAL field.
    svc.save_section(CID, IntakeSection.IDENTITY, {"full_name": "Janet Different"})
    p = tmp_path / "resume.txt"
    p.write_text(_RESUME, encoding="utf-8")
    result = svc.ingest_base_resume(CID, str(p))
    # FR-FB-3: integral change is NOT auto-applied; surfaced as a conflict.
    assert any(c.attribute == "full_name" for c in result.conflicts)
    assert "full_name" not in result.auto_applied
    state = svc.get_state(CID)
    assert state.intake[IntakeSection.IDENTITY.value]["full_name"] == "Janet Different"


def test_confirm_conflict_applies_integral_change(svc_and_storage, tmp_path):
    svc, storage, _ = svc_and_storage
    svc.save_section(CID, IntakeSection.IDENTITY, {"full_name": "Janet Different"})
    p = tmp_path / "resume.txt"
    p.write_text(_RESUME, encoding="utf-8")
    svc.ingest_base_resume(CID, str(p))
    svc.confirm_conflict(CID, "full_name", "Jane Q Candidate")
    state = svc.get_state(CID)
    assert state.intake[IntakeSection.IDENTITY.value]["full_name"] == "Jane Q Candidate"
    attrs = {a.name: a for a in storage.attributes.list_for_campaign(CampaignId(CID))}
    assert attrs["full_name"].value == "Jane Q Candidate"
    assert attrs["full_name"].is_integral is True
