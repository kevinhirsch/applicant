"""ATS abstraction tests (FR-PREFILL-2, NFR-EXT-1).

The ATS abstraction must let new ATSes follow without core changes: a new adapter
is a subclass registered in ``ATS_REGISTRY`` and resolved by URL. The Workday
adapter models the real multi-page flow shape with the irreducible-human-step
pages flagged and the sensitive/screening fields tagged.
"""

from __future__ import annotations

import pytest

from applicant.adapters.browser.ats import (
    ATS_REGISTRY,
    SCREENING_ESSAY,
    SCREENING_FACTUAL,
    AshbyAts,
    BambooHrAts,
    BrassRingAts,
    GenericAts,
    GreenhouseAts,
    JobviteAts,
    LeverAts,
    SmartRecruitersAts,
    SuccessFactorsAts,
    TaleoAts,
    WorkdayAts,
    resolve_ats,
    resolve_ats_strict,
)
from applicant.core.rules.sensitive_fields import (
    is_sensitive_field,
    is_work_auth_question,
)

WORKDAY_URL = "https://acme.myworkdayjobs.com/job/123"


@pytest.mark.unit
class TestWorkdayAts:
    def test_flow_shape_account_then_eeo_then_submit(self):
        pages = WorkdayAts().pages(WORKDAY_URL)
        assert pages[0].is_account_create is True
        assert pages[-1].is_final_submit is True
        # Exactly one account-create and one final-submit page (the boundary pages).
        assert sum(p.is_account_create for p in pages) == 1
        assert sum(p.is_final_submit for p in pages) == 1

    def test_has_sensitive_eeo_fields(self):
        labels = [f.label.lower() for p in WorkdayAts().pages(WORKDAY_URL) for f in p.fields]
        assert any("gender" in label for label in labels)
        assert any("veteran" in label for label in labels)

    def test_has_both_screening_question_kinds(self):
        types = {f.field_type for p in WorkdayAts().pages(WORKDAY_URL) for f in p.fields}
        assert SCREENING_FACTUAL in types
        assert SCREENING_ESSAY in types

    def test_tenant_key_is_per_host(self):
        a = WorkdayAts().tenant_key("https://acme.myworkdayjobs.com/x")
        b = WorkdayAts().tenant_key("https://other.myworkdayjobs.com/x")
        assert a != b
        assert a.startswith("workday:")


@pytest.mark.unit
class TestAtsResolution:
    def test_workday_url_resolves_to_workday(self):
        assert isinstance(resolve_ats(WORKDAY_URL), WorkdayAts)

    def test_greenhouse_url_resolves_to_greenhouse(self):
        adapter = resolve_ats("https://boards.greenhouse.io/acme/jobs/1")
        assert isinstance(adapter, GreenhouseAts)

    def test_unknown_url_resolves_to_generic_driver(self):
        # #173: 1.0 commits to UNIVERSAL coverage — an unknown ATS resolves to the
        # vendor-agnostic GENERIC live-DOM driver, NOT the Workday fixed-page model
        # (which would mis-apply the wrong page shape) (FR-PREFILL-2).
        resolved = resolve_ats("https://unknown.example/apply")
        assert isinstance(resolved, GenericAts)
        assert not isinstance(resolved, WorkdayAts)
        # The generic driver imposes no fixed multi-page model: a single live-DOM page
        # ending on final submit, with no hard-coded account-create gate.
        pages = resolved.pages("https://unknown.example/apply")
        assert len(pages) == 1
        assert pages[-1].is_final_submit is True
        assert not any(p.is_account_create for p in pages)

    def test_strict_resolver_returns_none_for_unknown(self):
        # #173: the strict resolver does not default to anything — None for an unknown
        # ATS (so an unrecognized ATS is still detectable), the vendor for a match.
        assert resolve_ats_strict("https://unknown.example/apply") is None
        assert isinstance(resolve_ats_strict(WORKDAY_URL), WorkdayAts)

    def test_generic_is_not_in_registry(self):
        # GenericAts is the explicit fallback, not a URL-matched registry entry.
        assert "generic" not in ATS_REGISTRY
        assert GenericAts().matches(WORKDAY_URL) is False

    def test_registry_is_extensible(self):
        # NFR-EXT-1: a new ATS = a new registry entry, no core change.
        assert "workday" in ATS_REGISTRY
        assert "greenhouse" in ATS_REGISTRY
        assert "lever" in ATS_REGISTRY  # Phase 4 added shape, no core change

    def test_greenhouse_has_no_account_page(self):
        pages = GreenhouseAts().pages("https://boards.greenhouse.io/acme/jobs/1")
        assert not any(p.is_account_create for p in pages)
        assert pages[-1].is_final_submit is True


@pytest.mark.unit
class TestLeverAts:
    """A THIRD ATS shape added in Phase 4 purely by subclassing (NFR-EXT-1)."""

    URL = "https://jobs.lever.co/acme/abc-123"

    def test_lever_url_resolves_to_lever(self):
        assert isinstance(resolve_ats(self.URL), LeverAts)

    def test_no_account_page_and_final_submit(self):
        pages = LeverAts().pages(self.URL)
        assert not any(p.is_account_create for p in pages)
        assert pages[-1].is_final_submit is True

    def test_has_both_screening_kinds_and_sensitive_field(self):
        pages = LeverAts().pages(self.URL)
        types = {f.field_type for p in pages for f in p.fields}
        assert SCREENING_FACTUAL in types and SCREENING_ESSAY in types
        labels = [f.label.lower() for p in pages for f in p.fields]
        assert any("gender" in lbl for lbl in labels)  # EEO field present

    def test_tenant_key_is_per_tenant(self):
        a = LeverAts().tenant_key("https://jobs.lever.co/acme/abc")
        b = LeverAts().tenant_key("https://jobs.lever.co/globex/xyz")
        assert a == "lever:acme" and b == "lever:globex"


# === Additional hand-coded adapters (Skyvern-parity gap #4, epic #351) ======
#
# Each row is (adapter class, sample URL, has_account_create). The four modern
# direct-apply ATSes carry NO account gate; the three enterprise ATSes gate the
# application behind account creation (an irreducible human step).
_NEW_ATS_CASES = [
    (AshbyAts, "https://jobs.ashbyhq.com/acme/1a2b3c", False),
    (SmartRecruitersAts, "https://jobs.smartrecruiters.com/Acme/74000-eng", False),
    (JobviteAts, "https://jobs.jobvite.com/acme/job/oABCdef", False),
    (BambooHrAts, "https://acme.bamboohr.com/careers/42", False),
    (TaleoAts, "https://acme.taleo.net/careersection/2/jobdetail.ftl?job=9", True),
    (
        SuccessFactorsAts,
        "https://career5.successfactors.com/careers?company=acme&pid=1",
        True,
    ),
    (
        BrassRingAts,
        "https://sjobs.brassring.com/TGnewUI/Search/Home/Home?partnerid=1&siteid=2",
        True,
    ),
]


@pytest.mark.unit
@pytest.mark.parametrize("cls, url, has_account", _NEW_ATS_CASES)
class TestAdditionalAtsAdapters:
    """Every new adapter: URL detection, boundary flags, and protected-class
    routing must be correct — mirrors the Workday/Lever contract tests."""

    def test_url_resolves_to_this_adapter(self, cls, url, has_account):
        # Both the public resolver and the strict resolver land on the adapter.
        assert isinstance(resolve_ats(url), cls)
        assert isinstance(resolve_ats_strict(url), cls)

    def test_registered_under_its_name(self, cls, url, has_account):
        assert ATS_REGISTRY.get(cls.name) is cls

    def test_exactly_one_final_submit_and_it_is_last(self, cls, url, has_account):
        pages = cls().pages(url)
        # The terminal review page is the ONLY final-submit boundary.
        assert pages[-1].is_final_submit is True
        assert sum(p.is_final_submit for p in pages) == 1
        # A final-submit page must never carry fillable fields (nothing to fill
        # past the stop boundary).
        assert pages[-1].fields == ()

    def test_account_create_boundary_is_correct(self, cls, url, has_account):
        pages = cls().pages(url)
        n_account = sum(p.is_account_create for p in pages)
        if has_account:
            # Enterprise ATS: exactly one account-create page, and it is FIRST
            # (the gate the pre-fill loop must stop at before proceeding).
            assert n_account == 1
            assert pages[0].is_account_create is True
        else:
            # Direct-apply ATS: NO phantom account-create page.
            assert n_account == 0
        # An account-create page is never also a final-submit page.
        assert not any(p.is_account_create and p.is_final_submit for p in pages)

    def test_eeo_fields_route_to_protected_path(self, cls, url, has_account):
        # The EEO/demographic labels must be recognised as sensitive by the real
        # core rule, so pre-fill never AI-guesses them (FR-ATTR-6).
        labels = [f.label for p in cls().pages(url) for f in p.fields]
        eeo = [lbl for lbl in labels if is_sensitive_field(lbl)]
        assert any("gender" in lbl.lower() for lbl in eeo)
        assert any("veteran" in lbl.lower() for lbl in eeo)
        assert any("disability" in lbl.lower() for lbl in eeo)

    def test_work_auth_question_routes_to_protected_path(self, cls, url, has_account):
        # The work-authorisation question must be recognised by the real core
        # rule, so it is answered only from the user's own stored answer.
        labels = [f.label for p in cls().pages(url) for f in p.fields]
        assert any(is_work_auth_question(lbl) for lbl in labels)

    def test_has_both_screening_kinds(self, cls, url, has_account):
        types = {f.field_type for p in cls().pages(url) for f in p.fields}
        assert SCREENING_FACTUAL in types
        assert SCREENING_ESSAY in types

    def test_no_sensitive_label_leaks_into_screening_type(
        self, cls, url, has_account
    ):
        # Belt-and-braces: a field tagged as a screening question must not ALSO
        # be a sensitive EEO label (which would misroute it to the LLM path).
        for page in cls().pages(url):
            for f in page.fields:
                if f.field_type in (SCREENING_FACTUAL, SCREENING_ESSAY):
                    assert not is_sensitive_field(f.label)

    def test_attribute_selectors_are_valid_closed_css(self, cls, url, has_account):
        # Regression: an EEO attribute selector like `select[name=eeo_gender` with
        # no closing `]` is invalid CSS — Playwright rejects it and the PROTECTED
        # field records a fill FAILURE instead of being prefilled. Every emitted
        # `[...]` attribute selector must be balanced/closed.
        for page in cls().pages(url):
            for f in page.fields:
                sel = f.selector
                assert sel.count("[") == sel.count("]"), (
                    f"unbalanced brackets in selector {sel!r} on {cls.__name__}"
                )
                if "[" in sel:
                    assert sel.rstrip().endswith("]"), (
                        f"unclosed attribute selector {sel!r} on {cls.__name__}"
                    )


@pytest.mark.unit
class TestAdditionalAtsRegistry:
    def test_all_seven_registered_without_clobbering_builtins(self):
        for name in (
            "ashby",
            "smartrecruiters",
            "jobvite",
            "bamboohr",
            "taleo",
            "successfactors",
            "brassring",
        ):
            assert name in ATS_REGISTRY
        # The original built-ins are still present (append-only, no clobber).
        for name in ("workday", "greenhouse", "lever", "icims"):
            assert name in ATS_REGISTRY

    def test_generic_still_the_fallback_for_unknown(self):
        # Adding vendors must not change the unknown-ATS fallback behaviour.
        assert isinstance(resolve_ats("https://unknown.example/apply"), GenericAts)
        assert resolve_ats_strict("https://unknown.example/apply") is None

    def test_tenant_keys_are_per_tenant(self):
        assert AshbyAts().tenant_key(
            "https://jobs.ashbyhq.com/acme/x"
        ) != AshbyAts().tenant_key("https://jobs.ashbyhq.com/globex/y")
        assert BambooHrAts().tenant_key(
            "https://acme.bamboohr.com/careers/1"
        ) == "bamboohr:acme"
        assert SmartRecruitersAts().tenant_key(
            "https://jobs.smartrecruiters.com/Acme/1"
        ) == "smartrecruiters:Acme"
