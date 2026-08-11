"""Unit tests for applicant.core.rules.role_domain_fit (role domain-fit gate).

Pure, deterministic, no IO — see the module docstring for the ALLOWLIST
design (a posting can be viable ONLY if its title plainly matches an
IN_DOMAIN role family; OUT_OF_DOMAIN and UNCLASSIFIED are gated identically
via :func:`is_allowlisted`) and the precedence rules. This suite is the
ROCK-SOLID deterministic layer the catastrophic scoring-miscalibration fix
depends on: a first, denylist-only version of this gate was deployed and
re-scored against the live queue, and the queue was STILL dominated by
garbage the denylist had no name for (YC "is hiring" announcements, a bare
platform name, "Sr. Zendesk Developer", "Market Manager", "Partner Director
- EMEA", ...) because it fell through UNCLASSIFIED to an LLM that cannot
reliably discriminate for this narrow a profile. This gate must NOT rely on
an LLM to hold the line.
"""

from __future__ import annotations

import pytest

from applicant.core.rules.role_domain_fit import (
    RoleDomainVerdict,
    classify_role_domain,
    is_allowlisted,
)


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
            "Enterprise Agile Coach",
            "Principal Agile Coach",
            "Agility Coach",
            "Scrum Coach",
            "Kanban Coach",
            "Agile Delivery Lead",
            "Agile Delivery Manager",
            "Agile Transformation Lead",
            "Director of Agile Transformation",
            "Agile Transformation Coach",
            "Ways of Working Lead",
            "Head of Ways of Working",
            # === ROUND 3 WIDENING: Program/Project mgmt, PMO, operations ===
            "Program Manager, Robotics",
            "Senior Program Manager",
            "Staff Program Manager",
            "Principal Program Manager",
            "Project Manager",
            "Senior Project Manager",
            "Lead Project Manager",
            "PMO Lead",
            "PMO Manager",
            "Delivery Operations Manager",
            "Product Operations Lead",
            "Program Operations Manager",
        ],
    )
    def test_title_is_in_domain(self, title: str) -> None:
        verdict = classify_role_domain(title)
        assert verdict.in_domain is True, verdict.reason
        assert is_allowlisted(verdict) is True, verdict.reason

    def test_engineering_manager_with_explicit_agile_delivery_is_in_domain(self) -> None:
        # "generic Engineering Manager" is out-of-domain "unless explicitly
        # agile-delivery" — the IN_DOMAIN phrase "Agile Delivery" must win.
        verdict = classify_role_domain("Engineering Manager, Agile Delivery")
        assert verdict.in_domain is True, verdict.reason

    def test_bare_program_manager_with_agile_context_in_title_is_in_domain(self) -> None:
        # "Agile Transformation" is itself now an unconditional in-domain
        # pattern, so this resolves via the generic in-domain-title branch
        # rather than the bare-Program-Manager-with-context special case --
        # either way the outcome (allowed through) is what matters here.
        verdict = classify_role_domain("Program Manager - Agile Transformation Office")
        assert verdict.in_domain is True, verdict.reason

    def test_bare_program_manager_is_now_unconditionally_in_domain(self) -> None:
        # ROUND 3 WIDENING: "Program Manager" (bare, no agile qualifier) is
        # now unconditionally in-domain -- Kevin is open to any fully-remote
        # role he can credibly do, not just agile-flavored ones. This
        # SUPERSEDES the round-2 "needs agile context" requirement.
        verdict = classify_role_domain("Senior Program Manager, Scrum Delivery")
        assert verdict.in_domain is True, verdict.reason
        assert verdict.signal == "in_domain_title"

    def test_chief_of_staff_with_delivery_context_is_in_domain(self) -> None:
        # Exercises the NEW conditional-with-context branch (round 3) --
        # Chief of Staff / Operations Manager/Lead are too generic to admit
        # unconditionally, so they need delivery/program/agile context.
        verdict = classify_role_domain(
            "Chief of Staff", description="Support the VP of Delivery with agile program management."
        )
        assert verdict.in_domain is True, verdict.reason
        assert verdict.signal == "in_domain_conditional_with_context"

    def test_operations_lead_with_pmo_context_is_in_domain(self) -> None:
        verdict = classify_role_domain(
            "Business Operations Lead", description="Own delivery cadence and PMO reporting for the org."
        )
        assert verdict.in_domain is True, verdict.reason

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
            "Sr. Zendesk Developer",
            "Senior Salesforce Engineer",
            "Affiliate EAP Counsellor",
            "Market Manager",
            "Startup Partnerships Lead",
            "Partner Director - EMEA",
            # === ROUND 3 WIDENING: newly-named categories ===
            "Registered Nurse",
            "Physician Assistant",
            "Clinical Research Coordinator",
            "Licensed Therapist",
            "Electrician",
            "Plumber",
            "HVAC Technician",
        ],
    )
    def test_additional_out_of_domain_categories(self, title: str) -> None:
        verdict = classify_role_domain(title)
        assert verdict.in_domain is False, verdict.reason
        assert is_allowlisted(verdict) is False, verdict.reason

    def test_generic_engineering_manager_without_agile_context_is_out_of_domain(self) -> None:
        verdict = classify_role_domain("Manager, Software Engineering - DevEx AI Tools")
        assert verdict.in_domain is False, verdict.reason


@pytest.mark.unit
class TestUnclassifiedTitles:
    """Neither list matches -> UNCLASSIFIED (``in_domain=None``).

    Under the CURRENT allowlist posture (see module docstring), UNCLASSIFIED
    is gated EXACTLY like OUT_OF_DOMAIN -- ``is_allowlisted()`` returns
    False for both. (An earlier denylist-only version of this gate let
    UNCLASSIFIED pass through un-gated; that was the bug the coordinator's
    live re-score caught -- YC "is hiring" announcements, "Market Manager",
    "Partner Director - EMEA" etc. all fell through unclassified and were
    then scored ~100 by an LLM that cannot discriminate this narrow a
    profile. See ``TestRealQueueGarbageIsNeverAllowlisted`` below.)
    """

    def test_bare_engineer_is_unclassified_and_gated(self) -> None:
        verdict = classify_role_domain("Engineer")
        assert verdict.in_domain is None, verdict.reason
        assert is_allowlisted(verdict) is False

    def test_bare_manager_is_unclassified_and_gated(self) -> None:
        verdict = classify_role_domain("Manager")
        assert verdict.in_domain is None, verdict.reason
        assert is_allowlisted(verdict) is False

    def test_operations_manager_without_delivery_context_is_unclassified_and_gated(
        self,
    ) -> None:
        # ROUND 3: "Operations Manager" is a CONDITIONAL title -- no
        # delivery/program/agile context anywhere means it stays gated
        # (unlike the now-unconditional "Program Manager", see
        # TestInDomainTitles.test_bare_program_manager_is_now_unconditionally_in_domain).
        verdict = classify_role_domain("Operations Manager", description="Manage warehouse operations.")
        assert verdict.in_domain is None, verdict.reason
        assert verdict.signal == ""
        assert is_allowlisted(verdict) is False

    def test_bare_portfolio_manager_is_unclassified_and_gated(self) -> None:
        # Deliberately NOT on the allowlist -- collides with the common
        # FINANCE/investment-management "Portfolio Manager" title. Only the
        # unambiguous "Program/Portfolio Delivery Manager" compound is
        # covered, via the "Delivery Manager" pattern.
        verdict = classify_role_domain("Portfolio Manager", description="Manage an investment portfolio.")
        assert verdict.in_domain is None, verdict.reason
        assert is_allowlisted(verdict) is False

    def test_unrelated_title_is_unclassified_and_gated(self) -> None:
        verdict = classify_role_domain("Warehouse Associate")
        assert verdict.in_domain is None, verdict.reason
        assert is_allowlisted(verdict) is False

    def test_empty_title_is_unclassified_and_gated(self) -> None:
        verdict = classify_role_domain("")
        assert verdict.in_domain is None, verdict.reason
        assert is_allowlisted(verdict) is False


@pytest.mark.unit
class TestRealQueueGarbageIsNeverAllowlisted:
    """The exact titles the coordinator's live re-score found STILL scoring
    ~98-100 after the first (denylist-only) version of this gate shipped --
    every one of these is UNCLASSIFIED under the old posture (none match a
    named OUT_OF_DOMAIN family) and MUST now be rejected by is_allowlisted()
    regardless of whether classify_role_domain calls it False or None."""

    @pytest.mark.parametrize(
        "title",
        [
            "LinkedIn",
            "Sr. Zendesk Developer",
            "Senior Salesforce Engineer",
            "Affiliate EAP Counsellor",
            "Market Manager",
            "Startup Partnerships Lead",
            "Partner Director - EMEA",
            "UpCodes is hiring remote Account Executives",
        ],
    )
    def test_real_queue_garbage_title_is_never_allowlisted(self, title: str) -> None:
        verdict = classify_role_domain(title)
        assert is_allowlisted(verdict) is False, (
            f"{title!r} must be gated, got in_domain={verdict.in_domain} "
            f"({verdict.reason})"
        )


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
