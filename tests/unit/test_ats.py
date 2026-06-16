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
    GreenhouseAts,
    WorkdayAts,
    resolve_ats,
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

    def test_unknown_url_defaults_to_workday(self):
        # MVP-1 ships Workday; unknown ATSes default to it (FR-PREFILL-2).
        assert isinstance(resolve_ats("https://unknown.example/apply"), WorkdayAts)

    def test_registry_is_extensible(self):
        # NFR-EXT-1: a new ATS = a new registry entry, no core change.
        assert "workday" in ATS_REGISTRY
        assert "greenhouse" in ATS_REGISTRY

    def test_greenhouse_has_no_account_page(self):
        pages = GreenhouseAts().pages("https://boards.greenhouse.io/acme/jobs/1")
        assert not any(p.is_account_create for p in pages)
        assert pages[-1].is_final_submit is True
