"""Round-2 audit #16 / §7.1 — "Parse the uploaded resume to pre-fill the profile".

Reachability investigation found the resume-parse -> reconcile -> prefill pipeline
(FR-ONBOARD-3) already fully built and wired end to end: the OOBE wizard's resume
step (workspace/static/js/applicantOnboarding.js `_renderBaseResume`) already posts
to the engine's `/base-resume` endpoint, shows visible feedback ("Read N details
from your resume — we've filled in the next steps for you to review"), surfaces
integral conflicts for explicit confirmation, and the subsequent intake steps
render pre-filled from the parse.

The one genuine gap: `OnboardingService._prefill_sections_from_parse` only ever
seeded the work-history / education intake forms with the MOST RECENT parsed
role/degree (a flat single-entry dict) even though those forms are REPEATABLE
(`SECTION_FORMS.work_history/education` in the wizard, `repeat: true`) and the
resume parser already extracts every role/degree it finds. Anyone with more than
one job or degree on their resume — i.e. almost everyone — still had to hand-type
every entry but the first, undercutting the entire "cut the OOBE typing tax" point
of this item.

This test covers the fix: a multi-job, multi-degree resume prefills an `entries`
list carrying EVERY parsed role/degree (the same `{"entries": [...]}` shape the
wizard already round-trips), not just the first one.
"""

from __future__ import annotations

import pytest

from applicant.adapters.resume_parser.resume_parser import ResumeParser
from applicant.adapters.storage.app_config_store import InMemoryAppConfigStore
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.onboarding_service import OnboardingService
from applicant.core.entities.campaign import Campaign
from applicant.core.ids import CampaignId
from applicant.ports.driving.onboarding import IntakeSection

CID = "camp-multi"

_MULTI_JOB_RESUME = """\
Jane Q Candidate
jane@example.com | +1 (415) 555-0199

Experience:
Senior Engineer at Acme Corp    Jan 2020 - Present
Software Engineer at Beta Inc    Jun 2016 - Dec 2019

Education:
M.S. Computer Science, State University    2018 - 2020
B.S. Computer Science, Older University    2012 - 2016

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


def test_multi_job_resume_prefills_every_role_not_just_the_first(svc_and_storage, tmp_path):
    """A 2-job resume prefills BOTH roles as `entries`, not just the most recent."""
    svc, *_ = svc_and_storage
    p = tmp_path / "resume.txt"
    p.write_text(_MULTI_JOB_RESUME, encoding="utf-8")

    svc.ingest_base_resume(CID, str(p))
    intake = svc.get_state(CID).intake

    wh = intake[IntakeSection.WORK_HISTORY.value]
    assert "entries" in wh, "work-history prefill must use the repeatable {entries: [...]} shape"
    entries = wh["entries"]
    assert len(entries) == 2, f"expected both parsed roles carried over, got {entries!r}"
    assert entries[0]["title"] == "Senior Engineer"
    assert entries[0]["company"] == "Acme Corp"
    assert entries[1]["title"] == "Software Engineer"
    assert entries[1]["company"] == "Beta Inc"


def test_multi_degree_resume_prefills_every_degree_not_just_the_first(svc_and_storage, tmp_path):
    """A 2-degree resume prefills BOTH degrees as `entries`, not just the most recent."""
    svc, *_ = svc_and_storage
    p = tmp_path / "resume.txt"
    p.write_text(_MULTI_JOB_RESUME, encoding="utf-8")

    svc.ingest_base_resume(CID, str(p))
    intake = svc.get_state(CID).intake

    edu = intake[IntakeSection.EDUCATION.value]
    assert "entries" in edu, "education prefill must use the repeatable {entries: [...]} shape"
    entries = edu["entries"]
    assert len(entries) == 2, f"expected both parsed degrees carried over, got {entries!r}"
    assert entries[0]["degree"] == "M.S. Computer Science"
    assert entries[1]["degree"] == "B.S. Computer Science"


def test_multi_entry_prefill_still_respects_dont_clobber_typed_values(svc_and_storage, tmp_path):
    """Re-uploading never overwrites a work-history section the user already typed,
    even in the new repeatable `entries` shape."""
    svc, *_ = svc_and_storage
    svc.save_section(
        CID,
        IntakeSection.WORK_HISTORY,
        {"entries": [{"title": "My Real Title", "company": "My Co"}]},
    )
    p = tmp_path / "resume.txt"
    p.write_text(_MULTI_JOB_RESUME, encoding="utf-8")
    svc.ingest_base_resume(CID, str(p))
    wh = svc.get_state(CID).intake[IntakeSection.WORK_HISTORY.value]
    assert wh["entries"][0]["title"] == "My Real Title"  # user's value preserved
    assert len(wh["entries"]) == 1  # not clobbered with the 2 parsed roles
