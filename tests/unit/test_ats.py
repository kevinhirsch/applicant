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
    GenericAts,
    GreenhouseAts,
    LeverAts,
    WorkdayAts,
    resolve_ats,
    resolve_ats_strict,
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
