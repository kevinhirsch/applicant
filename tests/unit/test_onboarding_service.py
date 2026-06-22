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


def test_fr_onboard_1_base_resume_and_references_are_required(svc_and_storage):
    """FR-ONBOARD-1: onboarding cannot complete without the base resume + references.

    Without the base resume the attribute cloud can't be bootstrapped and the
    FR-ONBOARD-3 reconciliation would be silently skipped, so both sit in
    REQUIRED_SECTIONS and gate completion.
    """
    svc, *_ = svc_and_storage
    assert IntakeSection.BASE_RESUME in REQUIRED_SECTIONS
    assert IntakeSection.REFERENCES in REQUIRED_SECTIONS

    # Fill every required section EXCEPT the base resume -> still incomplete.
    for section in REQUIRED_SECTIONS:
        if section is IntakeSection.BASE_RESUME:
            continue
        svc.save_section(CID, section, {"x": "value"})
    state = svc.complete(CID)
    assert state.complete is False
    assert IntakeSection.BASE_RESUME.value in state.missing_sections

    # Provide the base resume -> now completion succeeds.
    svc.save_section(CID, IntakeSection.BASE_RESUME, {"document_path": "/tmp/r.pdf"})
    assert svc.complete(CID).complete is True


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


def test_phone_format_difference_is_not_a_conflict(svc_and_storage, tmp_path):
    """A phone written in a different format is the SAME number — not a conflict.

    Regression for the false-conflict bug: the user states ``3146695386`` and the
    resume has ``(314) 669-5386``; format-only differences must not be flagged.
    """
    svc, storage, _ = svc_and_storage
    # User typed the phone digits-only; resume has it formatted (note the area
    # code matches the resume below so this is a true format-only difference).
    resume = (
        "Jane Q Candidate\n"
        "jane@example.com | (415) 555-0199\n"
    )
    svc.save_section(CID, IntakeSection.IDENTITY, {"phone": "4155550199"})
    p = tmp_path / "resume.txt"
    p.write_text(resume, encoding="utf-8")
    result = svc.ingest_base_resume(CID, str(p))
    # No phone conflict surfaced — same number, different format.
    assert not any(c.attribute == "phone" for c in result.conflicts)


def test_phone_genuinely_different_is_still_a_conflict(svc_and_storage, tmp_path):
    """A genuinely different phone number IS still surfaced for confirmation."""
    svc, *_ = svc_and_storage
    resume = "Jane Q Candidate\njane@example.com | (415) 555-0199\n"
    svc.save_section(CID, IntakeSection.IDENTITY, {"phone": "(212) 000-0000"})
    p = tmp_path / "resume.txt"
    p.write_text(resume, encoding="utf-8")
    result = svc.ingest_base_resume(CID, str(p))
    assert any(c.attribute == "phone" for c in result.conflicts)


def test_resume_first_prefills_editable_intake_fields(svc_and_storage, tmp_path):
    """Resume-first: uploading the resume FIRST prefills the editable intake forms.

    The user should NOT have to type everything by hand — the parse populates the
    identity / work-history / education / skills intake under the wizard's own
    field names, ready to review and correct.
    """
    svc, *_ = svc_and_storage
    p = tmp_path / "resume.txt"
    p.write_text(_RESUME, encoding="utf-8")
    # No interview answers entered yet — resume is the starting point.
    svc.ingest_base_resume(CID, str(p))
    intake = svc.get_state(CID).intake

    # Identity prefilled under the WIZARD's field names (so the form renders filled).
    identity = intake[IntakeSection.IDENTITY.value]
    assert identity.get("full_legal_name") == "Jane Q Candidate"
    assert identity.get("email") == "jane@example.com"
    assert identity.get("phone")  # parsed from the resume

    # Structured sections prefilled too (flat single-entry forms in the wizard).
    wh = intake[IntakeSection.WORK_HISTORY.value]
    assert wh.get("title") == "Senior Engineer"
    assert wh.get("company") == "Acme Corp"

    edu = intake[IntakeSection.EDUCATION.value]
    assert "Computer Science" in edu.get("degree", "") or edu.get("degree")

    skills = intake[IntakeSection.KEY_ATTRIBUTES.value]
    assert "Python" in skills.get("technical_skills", "")


def test_resume_first_prefill_does_not_clobber_typed_values(svc_and_storage, tmp_path):
    """Re-uploading never overwrites a value the user already typed."""
    svc, *_ = svc_and_storage
    svc.save_section(
        CID, IntakeSection.WORK_HISTORY, {"title": "My Real Title", "company": "My Co"}
    )
    p = tmp_path / "resume.txt"
    p.write_text(_RESUME, encoding="utf-8")
    svc.ingest_base_resume(CID, str(p))
    wh = svc.get_state(CID).intake[IntakeSection.WORK_HISTORY.value]
    assert wh.get("title") == "My Real Title"  # user's value preserved


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


# === #6: onboarding intake bridges into the engine ==========================
@pytest.mark.unit
def test_campaign_criteria_intake_flows_into_get_criteria(svc_and_storage):
    """#6: saving the CAMPAIGN_CRITERIA section flows the criteria into the
    CriteriaService so the loop's get_criteria sees it (not stranded in onboarding)."""
    from applicant.application.services.criteria_service import CriteriaService

    svc, storage, _store = svc_and_storage
    criteria = CriteriaService(storage, llm=None)
    svc.set_criteria_service(criteria)

    svc.save_section(
        CID,
        IntakeSection.CAMPAIGN_CRITERIA,
        {"titles": ["Staff Engineer"], "keywords": ["python"], "salary_floor": "150000"},
    )

    got = criteria.get_criteria(CampaignId(CID))
    assert "Staff Engineer" in got.titles
    assert "python" in got.keywords
    assert got.salary_floor == 150000


@pytest.mark.unit
def test_typed_intake_section_upserts_attributes(svc_and_storage):
    """#6: a typed intake section upserts into the attribute cloud."""
    from applicant.application.services.attribute_cloud_service import AttributeCloudService

    svc, storage, _store = svc_and_storage
    attrs = AttributeCloudService(storage)
    svc.set_attribute_cloud_service(attrs)

    svc.save_section(CID, IntakeSection.IDENTITY, {"full_name": "Jane Q"})

    stored = storage.attributes.list_for_campaign(CampaignId(CID))
    assert any(a.name == "full_name" and a.value == "Jane Q" for a in stored)
