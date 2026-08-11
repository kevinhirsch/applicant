"""Scoring-correctness wave (2026-08-11): verified-source ranking, title-aware
non-US gate, and senior agile-leadership allowlist recognition.

Each test pins a live-queue defect observed against Kevin's campaign:
- searxng SAFe/RTE web-hits dominated the top over verified ATS postings.
- "Senior TPM in Pune, India" (location in TITLE, null location column) scored
  0.7 because the US-remote gate never saw the title.
- CVS "Senior Manager, Agile Practice Management" scored 15 (floored) because
  the domain allowlist did not recognize senior agile-leadership titles.
"""

import pytest

from applicant.core.rules.ranking_factors import (
    classify_remote,
    fit_to_profile_multiplier,
    source_reliability_multiplier,
)
from applicant.core.rules.role_domain_fit import classify_role_domain, is_allowlisted


@pytest.mark.unit
class TestTitleAwareNonUsGate:
    def test_non_us_location_in_title_is_gated(self):
        # location carried in the TITLE, location column NULL (searxng shape)
        v = classify_remote(None, None, "", title="Senior Technical Program Manager in Pune, India")
        assert v.is_us_remote is False

    def test_non_us_city_country_in_title_is_gated(self):
        v = classify_remote(None, None, "", title="Agile Coach - Toronto, Canada")
        assert v.is_us_remote is False

    def test_company_name_containing_a_city_is_NOT_gated(self):
        # "London" is the company name, not a locative mention -> must NOT gate.
        v = classify_remote(None, None, "", title="London Stock Exchange - Scrum Master")
        assert v.is_us_remote is not False

    def test_us_remote_in_title_confirms_us(self):
        v = classify_remote(None, None, "", title="Scrum Master, Remote - US")
        assert v.is_us_remote is True

    def test_plain_title_stays_ambiguous_not_gated(self):
        v = classify_remote(None, None, "", title="Scrum Master")
        assert v.is_us_remote is None

    def test_foreign_office_in_description_does_not_gate_a_us_remote_role(self):
        # incidental "London office" in the JD body, with a US signal present.
        v = classify_remote("remote", "Remote - US", "collaborate with our London office", title="Agile Coach")
        assert v.is_us_remote is True


@pytest.mark.unit
class TestSourceReliabilityMultiplier:
    def test_verified_ats_sources_are_full_weight(self):
        for key in ("greenhouse:tide", "lever:x", "ashby:org", "smartrecruiters:co", "workday:nationwide"):
            assert source_reliability_multiplier(key).multiplier == 1.0, key

    def test_raw_searxng_is_demoted(self):
        f = source_reliability_multiplier("searxng:brave")
        assert f.multiplier == pytest.approx(0.72)
        # and strictly below any verified ATS source
        assert f.multiplier < source_reliability_multiplier("greenhouse:x").multiplier

    def test_medium_and_unknown_are_neutral(self):
        # Only raw searxng is demoted; real scraped sources (jobspy/rss) and
        # unknown sources stay neutral so no genuine posting is penalized.
        assert source_reliability_multiplier("jobspy:indeed").multiplier == pytest.approx(1.0)
        assert source_reliability_multiplier("").multiplier == pytest.approx(1.0)
        assert source_reliability_multiplier("rss:hn").multiplier == pytest.approx(1.0)


@pytest.mark.unit
class TestSeniorAgileLeadershipAllowlist:
    def test_agile_practice_management_is_in_domain(self):
        assert is_allowlisted(classify_role_domain("Senior Manager, Agile Practice Management"))

    def test_agile_leader_is_in_domain(self):
        assert is_allowlisted(classify_role_domain("Consultant, Agile Leader (Consultant, Scrum Master)"))

    def test_agile_practitioner_is_in_domain(self):
        # UHG/Optum "Agile Practitioner 2" (an RTE/Scrum Master role) -- "practice"
        # does not substring-match "practitioner", so the family pattern must.
        assert is_allowlisted(classify_role_domain("Agile Practitioner 2"))
        assert is_allowlisted(classify_role_domain("Senior Agile Practitioner"))

    def test_regression_scrum_master_still_in_domain(self):
        assert is_allowlisted(classify_role_domain("Scrum Master"))

    def test_regression_out_of_domain_still_rejected(self):
        assert not is_allowlisted(classify_role_domain("Registered Nurse, ICU"))


@pytest.mark.unit
class TestBigTechTpmReachTier:
    def test_leveled_tpm_is_a_reach(self):
        for t in (
            "Staff Technical Program Manager, Simulation",
            "Sr. Staff Technical Program Manager",
            "Senior Technical Program Manager, AI Transformation",
            "Lead Technical Program Manager, Simulation",
            "Principal Technical Program Manager",
        ):
            assert fit_to_profile_multiplier(t).multiplier == pytest.approx(0.65), t

    def test_plain_unleveled_tpm_stays_moderate_not_reach(self):
        # A PLAIN (unleveled) TPM is a stretch, not a leveled big-tech reach.
        assert fit_to_profile_multiplier("Technical Program Manager").multiplier == pytest.approx(0.85)

    def test_scrum_master_stays_strong_fit(self):
        assert fit_to_profile_multiplier("Senior Scrum Master").multiplier == pytest.approx(1.10)
