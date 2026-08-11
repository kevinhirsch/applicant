"""CandidateProfile entity contract (ADR-0011, FIT-MODEL FM-1)."""

import pytest

from applicant.core.entities.candidate_profile import (
    CandidateProfile,
    FitBand,
    TitleHistory,
)
from applicant.core.ids import CampaignId, new_id


@pytest.mark.unit
class TestCandidateProfileContract:
    def _cid(self) -> CampaignId:
        return CampaignId(new_id())

    def test_undrived_profile_never_classifies_so_callers_fall_back(self):
        # A sparse/un-derived profile must return None for band_for so scoring
        # degrades gracefully to the legacy allowlist (ADR-0012 migration).
        p = CandidateProfile(campaign_id=self._cid())
        assert p.derived is False
        assert p.band_for("scrum_master") is None
        assert p.held_families() == frozenset()

    def test_derived_bands_classify_strong_stretch_reach(self):
        p = CandidateProfile(
            campaign_id=self._cid(),
            title_history=(
                TitleHistory(title="Scrum Master", family="scrum_master", level="lead", years=10),
            ),
            strong_fit_families=(FitBand(family="scrum_master", rationale="title + certs match"),),
            viable_stretch_families=(FitBand(family="program_manager"),),
            reach_families=(FitBand(family="technical_program_manager"),),
            derived=True,
        )
        assert p.band_for("scrum_master") == "strong"
        assert p.band_for("SCRUM_MASTER") == "strong"  # family key is case-insensitive
        assert p.band_for("program_manager") == "stretch"
        assert p.band_for("technical_program_manager") == "reach"
        assert p.band_for("registered_nurse") is None
        assert p.held_families() == frozenset({"scrum_master"})

    def test_degree_gate_is_first_class(self):
        # "no bachelor's" is a hard ATS auto-filter -> explicit boolean field.
        p = CandidateProfile(campaign_id=self._cid(), has_degree=False, degree_detail="no bachelor's")
        assert p.has_degree is False
        assert "bachelor" in p.degree_detail
