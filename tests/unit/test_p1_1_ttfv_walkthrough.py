"""P1-1 — time-to-first-value: the scripted critical-path walkthrough.

The story's promise is that a brand-new user reaches first value (profile
parsed, search allowed to run) fast. These tests pin the ENGINE side of that
promise on the golden path and its failure states:

* the critical path is exactly THREE user actions — connect a model, upload a
  résumé, confirm search criteria — and the automated-work gate opens the
  moment the third lands (no hidden fourth step can creep in unnoticed);
* the résumé upload does the heavy lifting: identity, work history (including
  the achievement bullets — previously dropped), education and skills are all
  prefilled for review, never re-typed;
* the "UC Berkeley — 2013" single-year education case (named in the story's
  DoR) parses into the year field instead of polluting the institution name;
* every not-ready stage reports an actionable, honest missing list (the
  recovery action), never a bare closed gate.
"""

from __future__ import annotations

import pytest

from applicant.adapters.resume_parser.resume_parser import ResumeParser
from applicant.adapters.storage.app_config_store import InMemoryAppConfigStore
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.onboarding_service import OnboardingService
from applicant.application.services.setup_service import SetupService
from applicant.core.entities.campaign import Campaign
from applicant.core.entities.search_criteria import SearchCriteria
from applicant.core.ids import CampaignId
from applicant.ports.driving.onboarding import IntakeSection

CID = "camp-ttfv"

# A realistic small résumé: achievements under the role, a single-year degree.
_RESUME = """\
Jane Q Candidate
jane@example.com | +1 (415) 555-0199

Experience:
Senior Engineer at Acme Corp    Jan 2020 - Present
Resolved over 200 customer escalations per quarter across enterprise accounts.
Automated the ticket-triage pipeline, cutting median response time by 40%.

Education:
B.A. Economics, UC Berkeley — 2013

Skills:
Python, SQL, FastAPI
"""


class _Criteria:
    """A settable criteria snapshot (mirrors test_apply_readiness_gate)."""

    def __init__(self, criteria: SearchCriteria) -> None:
        self._criteria = criteria

    def set(self, criteria: SearchCriteria) -> None:
        self._criteria = criteria

    def get_criteria(self, campaign_id: CampaignId) -> SearchCriteria:
        return self._criteria


@pytest.fixture
def stack():
    storage = InMemoryStorage()
    storage.campaigns.add(Campaign(id=CampaignId(CID), name="c"))
    store = InMemoryAppConfigStore()
    onboarding = OnboardingService(
        storage=storage, config_store=store, resume_parser=ResumeParser()
    )
    criteria = _Criteria(SearchCriteria(campaign_id=CampaignId(CID)))
    onboarding.set_criteria_service(criteria)
    return onboarding, criteria, store


def _connect_model(onboarding) -> SetupService:
    """User action 1: connect a model (the only gate to BEGIN)."""
    setup = SetupService(
        llm_configured=True,
        config_store=InMemoryAppConfigStore(),
        onboarding_gate=lambda: onboarding.is_ready_to_apply(CID),
    )
    setup.set_apply_readiness_reporter(lambda: onboarding.apply_readiness(CID))
    return setup


def _confirm_criteria(criteria: _Criteria) -> None:
    """User action 3: confirm what to look for (one wizard section)."""
    criteria.set(
        SearchCriteria(
            campaign_id=CampaignId(CID),
            titles=("Software Engineer",),
            locations=("Remote",),
            work_modes=("remote",),
            salary_floor=120000,
            keywords=("python", "fastapi"),
        )
    )


def test_ttfv_golden_path_is_three_user_actions(stack, tmp_path):
    """Connect a model -> upload a résumé -> confirm criteria == gate OPEN.

    If a change ever adds a hidden fourth required action to the critical path,
    this walkthrough fails and the TTFV regression is caught before ship.
    """
    onboarding, criteria, _store = stack

    # Action 1: connect a model. Setup may begin; applying is still gated.
    setup = _connect_model(onboarding)
    assert setup.is_setup_gate_open() is True
    assert setup.is_automated_work_allowed() is False

    # Action 2: upload the résumé (parse + prefill in the same step).
    p = tmp_path / "resume.txt"
    p.write_text(_RESUME, encoding="utf-8")
    result = onboarding.ingest_base_resume(CID, str(p))
    assert result.parsed_field_count >= 3  # a real parse, honestly counted

    # Action 3: confirm search criteria.
    _confirm_criteria(criteria)

    # First value: the gate is open — the 24/7 loop may discover + digest.
    assert setup.is_automated_work_allowed() is True
    assert setup.apply_readiness().ready is True


def test_resume_upload_prefills_everything_reviewable(stack, tmp_path):
    """The upload seeds identity, work history (with achievements), education
    (single-year case included) and skills — the user reviews, never re-types."""
    onboarding, _criteria, _store = stack
    p = tmp_path / "resume.txt"
    p.write_text(_RESUME, encoding="utf-8")
    onboarding.ingest_base_resume(CID, str(p))
    intake = onboarding.get_state(CID).intake

    identity = intake[IntakeSection.IDENTITY.value]
    assert identity.get("full_legal_name") == "Jane Q Candidate"
    assert identity.get("email") == "jane@example.com"

    wh = intake[IntakeSection.WORK_HISTORY.value]["entries"][0]
    assert wh.get("title") == "Senior Engineer"
    assert wh.get("company") == "Acme Corp"
    # The achievement prose lands in the editable highlights field.
    assert "Resolved over 200 customer escalations" in wh.get("highlights", "")

    edu = intake[IntakeSection.EDUCATION.value]["entries"][0]
    # The single-year "UC Berkeley — 2013" case: year in the year field, the
    # institution clean — a bad parse here stays editable in the review form.
    assert edu.get("institution") == "UC Berkeley"
    assert edu.get("end_year") == "2013"

    skills = intake[IntakeSection.KEY_ATTRIBUTES.value]
    assert "Python" in skills.get("technical_skills", "")


def test_every_not_ready_stage_names_its_recovery(stack, tmp_path):
    """Failure states on the critical path carry an actionable missing list.

    An honest 'here is exactly what is left' IS the recovery action — the
    front door renders it (wizard banner, Today essentials checklist) instead
    of a silent closed gate.
    """
    onboarding, criteria, _store = stack
    setup = _connect_model(onboarding)

    # Stage: model connected, nothing else — the report names every essential.
    readiness = setup.apply_readiness()
    assert readiness.ready is False
    assert len(readiness.missing) >= 2
    assert readiness.reason  # plain-language, actionable
    assert "FR-" not in readiness.reason and "NFR-" not in readiness.reason

    # Stage: résumé in, criteria still missing — the list shrinks accordingly
    # and never claims the résumé again.
    p = tmp_path / "resume.txt"
    p.write_text(_RESUME, encoding="utf-8")
    onboarding.ingest_base_resume(CID, str(p))
    readiness = setup.apply_readiness()
    assert readiness.ready is False
    assert all("résumé" not in m and "resume" not in m for m in readiness.missing)

    # Stage: criteria confirmed — nothing missing, gate open.
    _confirm_criteria(criteria)
    assert setup.apply_readiness().ready is True
    assert setup.apply_readiness().missing == ()


def test_single_year_education_parses_clean_at_the_parser_level(tmp_path):
    """Parser-level pin for the DoR-named single-year case."""
    resume = (
        "Jane Q Candidate\n"
        "jane@example.com | (415) 555-0199\n\n"
        "Education:\n"
        "B.A. Economics, UC Berkeley — 2013\n"
    )
    p = tmp_path / "r.txt"
    p.write_text(resume, encoding="utf-8")
    parsed = ResumeParser().parse(str(p))
    assert len(parsed.education) == 1
    edu = parsed.education[0]
    assert edu.degree == "B.A. Economics"
    assert edu.institution == "UC Berkeley"
    assert edu.start_year == ""
    assert edu.end_year == "2013"
