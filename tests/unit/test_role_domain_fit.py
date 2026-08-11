"""Unit tests for applicant.core.rules.role_domain_fit (role domain-fit gate).

Pure, deterministic, no IO — see the module docstring for the IN_DOMAIN /
OUT_OF_DOMAIN / UNCLASSIFIED tri-state design and precedence rules. This
suite is the ROCK-SOLID deterministic layer the catastrophic scoring
miscalibration fix depends on (see the backlog item / incident report):
nearly every posting in the live queue scored 85-100 regardless of role
relevance, so this gate must NOT rely on an LLM to hold the line.
"""

from __future__ import annotations

import pytest

from applicant.core.rules.role_domain_fit import RoleDomainVerdict, classify_role_domain


@pytest.mark.unit
class TestInDomainTitles:
    @pytest.mark.parametrize(
        "title",
        [
            "Scrum Master",
            "Scrum Master - Enterprise Agile Transformation and Scaled Agile",
            "Senior Scrum Master / Release Train Engineer",
            "Scrum Master/Team Coach - Scaled Agile Framework",
            "Release Train Engineer (RTE) | Schwab Jobs",
            "Senior Release Train Engineer in Charlotte, North Carolina, USA",
            "Agile Coach and Release Train Engineer - Careers - Booz Allen",
            "Agile Coach - Enterprise Delivery",
            "Delivery Manager, Platform Engineering",
            "Senior Delivery Lead",
            "Iteration Manager",
            "Technical Program Manager, Agile Delivery & Release Management",
            "Senior TPM, Agile Program Management",
            "Agile Program Manager",
        ],
    )
    def test_title_is_in_domain(self, title: str) -> None:
        verdict = classify_role_domain(title)
        assert verdict.in_domain is True, verdict.reason

    def test_engineering_manager_with_explicit_agile_delivery_is_in_domain(self) -> None:
        # "generic Engineering Manager" is out-of-domain "unless explicitly
        # agile-delivery" — the IN_DOMAIN phrase "Agile Delivery" must win.
        verdict = classify_role_domain("Engineering Manager, Agile Delivery")
        assert verdict.in_domain is True, verdict.reason

    def test_bare_program_manager_with_agile_context_in_title_is_in_domain(self) -> None:
        verdict = classify_role_domain("Program Manager - Agile Transformation Office")
        assert verdict.in_domain is True, verdict.reason
        assert verdict.signal == "in_domain_program_manager_with_context"

    def test_bare_program_manager_with_agile_context_in_description_is_in_domain(self) -> None:
        verdict = classify_role_domain(
            "Senior Program Manager",
            description="You will run Scrum ceremonies and PI Planning across the org.",
        )
        assert verdict.in_domain is True, verdict.reason


@pytest.mark.unit
class TestOutOfDomainTitles:
    """The exact catastrophic-false-positive titles from the live queue."""

    @pytest.mark.parametrize(
        "title",
        [
            "Key Accounts Executive",
            "Engineering Manager, Serverless Compute",
            "Group Product Manager",
            "Sr. Manager Accounts Payable",
            "Senior Product Security Engineer II",
            "DevOps Engineer",
            "Senior Software Engineer",
            "Director Paid Media",
            "Senior Counsel",
            "Sr. Video Editor (short-form)",
            "Senior Product Designer",
            "Director Data Science",
            "Applied AI Architect",
            "Frontend Engineer",
            "Research Advisor",
            "Staff Product Manager AI Personalization",
        ],
    )
    def test_title_is_out_of_domain(self, title: str) -> None:
        verdict = classify_role_domain(title)
        assert verdict.in_domain is False, verdict.reason
        assert verdict.signal == "out_of_domain_title"

    @pytest.mark.parametrize(
        "title",
        [
            "Senior Backend Engineer",
            "Staff Platform Engineer",
            "Full-Stack Engineer",
            "Machine Learning Engineer",
            "Site Reliability Engineer",
            "Infrastructure Engineer",
            "Senior Data Engineer",
            "Data Scientist",
            "Applied AI Scientist",
            "Applied AI Researcher",
            "UX Designer",
            "UX Researcher",
            "Accountant",
            "Accounts Payable Specialist",
            "Finance Manager",
            "Corporate Counsel",
            "Account Executive, Enterprise Sales",
            "Marketing Manager",
        ],
    )
    def test_additional_out_of_domain_categories(self, title: str) -> None:
        verdict = classify_role_domain(title)
        assert verdict.in_domain is False, verdict.reason

    def test_generic_engineering_manager_without_agile_context_is_out_of_domain(self) -> None:
        verdict = classify_role_domain("Manager, Software Engineering - DevEx AI Tools")
        assert verdict.in_domain is False, verdict.reason


@pytest.mark.unit
class TestUnclassifiedTitles:
    """Neither list matches -> UNCLASSIFIED (None) -> callers must pass through
    to the normal LLM/embedding scoring path, never suppressing the score."""

    def test_bare_engineer_is_unclassified(self) -> None:
        verdict = classify_role_domain("Engineer")
        assert verdict.in_domain is None, verdict.reason

    def test_bare_manager_is_unclassified(self) -> None:
        verdict = classify_role_domain("Manager")
        assert verdict.in_domain is None, verdict.reason

    def test_bare_program_manager_with_no_context_anywhere_is_unclassified(self) -> None:
        verdict = classify_role_domain("Program Manager, Robotics")
        assert verdict.in_domain is None, verdict.reason
        assert verdict.signal == ""

    def test_unrelated_title_is_unclassified(self) -> None:
        verdict = classify_role_domain("Warehouse Associate")
        assert verdict.in_domain is None, verdict.reason

    def test_empty_title_is_unclassified(self) -> None:
        verdict = classify_role_domain("")
        assert verdict.in_domain is None, verdict.reason


@pytest.mark.unit
class TestPrecedenceAndEdgeCases:
    def test_in_domain_checked_before_out_of_domain(self) -> None:
        # Contains both "Delivery Manager" (in) and "Software Engineering"-
        # adjacent wording, but the in-domain phrase must win.
        verdict = classify_role_domain("Delivery Manager - Software Engineering Org")
        assert verdict.in_domain is True

    def test_technical_program_manager_off_domain_substance_still_classifies_in_domain_by_title(
        self,
    ) -> None:
        # Per the taxonomy, TPM/"Technical Program Manager" is unconditionally
        # IN_DOMAIN by TITLE — actual role-substance fit (e.g. a hands-on
        # technical builder TPM) is the LLM rubric's job (GATE 2), not this
        # gate's. This gate only prevents catastrophic mismatches, it never
        # promises a title-only match is actually a good fit.
        verdict = classify_role_domain("Senior Technical Program Manager, Robotics")
        assert verdict.in_domain is True

    def test_none_and_empty_inputs_do_not_raise(self) -> None:
        verdict = classify_role_domain(None, None)  # type: ignore[arg-type]
        assert isinstance(verdict, RoleDomainVerdict)
        assert verdict.in_domain is None

    def test_case_insensitive_matching(self) -> None:
        assert classify_role_domain("scrum master").in_domain is True
        assert classify_role_domain("DEVOPS ENGINEER").in_domain is False
