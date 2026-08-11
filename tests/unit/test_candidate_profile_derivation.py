"""Deterministic CandidateProfile derivation (ADR-0011, FIT-MODEL FM-2).

Grounded in Kevin's REAL attribute cloud so the derived bands match the human
judgment the hardcoded allowlist currently encodes — but DERIVED, so a different
candidate yields different bands.
"""

import pytest

from applicant.core.rules.candidate_profile_derivation import derive_candidate_profile
from applicant.core.ids import CampaignId, new_id

# Kevin's real education entries (verbatim shape from the live attribute cloud):
# certifications + secondary education, NO academic degree. The MOS cert is the
# key false-positive trap ("Master Specialist" must not read as a master's degree).
_KEVIN_EDUCATION = {
    "education:0": "Certified Scrum Professional - ScrumMaster (CSP-SM), Scrum Alliance",
    "education:1": "Advanced Certified ScrumMaster (A-CSM), Scrum Alliance",
    "education:2": "Certified ScrumMaster (CSM), Scrum Alliance",
    "education:3": "Certified SAFe 6 Scrum Master, Scaled Agile",
    "education:4": "Kanban Management Professional (KMP), Kanban University",
    "education:5": "Microsoft Office Master Specialist (MOS)",
    "education:6": "Seckman High School (2011 - 2014)",
    "education:7": "Homeschool (2011 - 2014)",
}
_KEVIN_ATTRS = {
    "roles": "Scrum Master, Release Train Engineer, Agile Coach",
    "certifications": "CSP-SM, A-CSM, CSM; SAFe 6 SSM; KMP",
    "skill:Large Scale Scrum (LeSS)": "Large Scale Scrum (LeSS)",
    "skill:Servant Leadership": "Servant Leadership",
    **_KEVIN_EDUCATION,
}


@pytest.mark.unit
class TestKevinDerivation:
    def _p(self):
        return derive_candidate_profile(CampaignId(new_id()), _KEVIN_ATTRS)

    def test_no_bachelors_master_specialist_cert_is_not_a_degree(self):
        p = self._p()
        assert p.derived is True
        assert p.has_degree is False  # the MOS "Master Specialist" trap must not trip
        assert "no academic degree" in p.degree_detail

    def test_held_roles_are_strong_fit(self):
        p = self._p()
        assert p.band_for("scrum_master") == "strong"
        assert p.band_for("release_train_engineer") == "strong"
        assert p.band_for("agile_coach") == "strong"
        assert p.held_families() >= {"scrum_master", "release_train_engineer", "agile_coach"}

    def test_program_project_management_is_a_stretch(self):
        p = self._p()
        assert p.band_for("program_manager") == "stretch"
        assert p.band_for("project_manager") == "stretch"

    def test_technical_program_manager_is_a_reach_no_title_no_degree(self):
        p = self._p()
        assert p.band_for("technical_program_manager") == "reach"

    def test_credentials_and_skills_populated(self):
        p = self._p()
        assert any("SAFe" in c.name for c in p.credentials)
        assert "Large Scale Scrum (LeSS)" in p.skills


@pytest.mark.unit
class TestGeneralization:
    def test_degree_holder_who_held_tpm_has_tpm_as_strong_not_reach(self):
        # A DIFFERENT candidate: held TPM + has a degree -> TPM is strong, not a reach.
        attrs = {
            "roles": "Technical Program Manager, Program Manager",
            "education:0": "Bachelor of Science in Computer Science, MIT",
        }
        p = derive_candidate_profile(CampaignId(new_id()), attrs)
        assert p.has_degree is True
        assert p.band_for("technical_program_manager") == "strong"
        assert p.band_for("technical_program_manager") != "reach"

    def test_empty_roles_degrades_to_undrived(self):
        p = derive_candidate_profile(CampaignId(new_id()), {"email": "x@y.com"})
        assert p.derived is False
        assert p.band_for("scrum_master") is None  # caller falls back to legacy allowlist
