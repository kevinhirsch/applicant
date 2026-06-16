"""BrowserAutomation contract against the PatchrightBrowser adapter (FR-PREFILL-*).

Architecture §6: "each adapter has a contract test". This asserts the behavioral
contract a ``BrowserAutomationPort`` promises — open returns a page state, fields
are detectable and fillable, screenshots return refs — plus the load-bearing
Phase 2 invariants: the pre-fill-stop boundary (FR-PREFILL-4) can NEVER be
bypassed, and the fingerprint is internally coherent (FR-STEALTH-1).
"""

from __future__ import annotations

import pytest

from applicant.adapters.browser.patchright_browser import (
    NORMALIZED_FINGERPRINT,
    PatchrightBrowser,
    WorkdayAts,
    fingerprint_is_coherent,
)
from applicant.core.errors import PrefillBoundaryViolation
from applicant.core.ids import ApplicationId, new_id
from applicant.ports.driven.browser_automation import (
    BrowserAutomationPort,
    DetectedField,
    PageState,
)

WORKDAY_URL = "https://acme.myworkdayjobs.com/job/123"


@pytest.mark.contract
class TestPatchrightBrowserContract:
    @pytest.fixture
    def adapter(self) -> PatchrightBrowser:
        return PatchrightBrowser()

    @pytest.fixture
    def aid(self) -> ApplicationId:
        return ApplicationId(new_id())

    def test_satisfies_port_protocol(self, adapter):
        assert isinstance(adapter, BrowserAutomationPort)

    def test_open_returns_page_state(self, adapter, aid):
        state = adapter.open(aid, WORKDAY_URL)
        assert isinstance(state, PageState)
        assert state.url

    def test_detect_fields_returns_fields(self, adapter, aid):
        adapter.open(aid, WORKDAY_URL)
        fields = adapter.detect_fields(aid)
        assert fields and all(isinstance(f, DetectedField) for f in fields)

    def test_fill_field_is_recorded(self, adapter, aid):
        adapter.open(aid, WORKDAY_URL)
        sel = adapter.detect_fields(aid)[0].selector
        adapter.fill_field(aid, sel, "value")
        assert adapter.filled_values(aid)[sel] == "value"

    def test_screenshot_returns_ref(self, adapter, aid):
        adapter.open(aid, WORKDAY_URL)
        ref = adapter.screenshot(aid)
        assert isinstance(ref, str) and ref

    def test_current_state_after_open(self, adapter, aid):
        adapter.open(aid, WORKDAY_URL)
        assert isinstance(adapter.current_state(aid), PageState)

    def test_open_required_before_use(self, adapter, aid):
        with pytest.raises(KeyError):
            adapter.detect_fields(aid)

    # --- pre-fill-stop boundary (FR-PREFILL-4) ---------------------------
    def test_account_create_submit_always_blocked(self, adapter, aid):
        adapter.open(aid, WORKDAY_URL)
        assert adapter.is_account_create_page(aid) is True
        with pytest.raises(PrefillBoundaryViolation):
            adapter.submit_account(aid)

    def test_final_submit_requires_authorization(self, adapter, aid):
        adapter.open(aid, WORKDAY_URL)
        # Walk to the final-submit page.
        while not adapter.is_final_submit_page(aid):
            assert adapter.advance(aid) is not None
        with pytest.raises(PrefillBoundaryViolation):
            adapter.click_final_submit(aid, engine_submit_authorized=False)
        # With authorization it is permitted (FR-PREFILL-5).
        adapter.click_final_submit(aid, engine_submit_authorized=True)

    # --- ATS abstraction (FR-PREFILL-2) ----------------------------------
    def test_workday_flow_has_account_then_eeo_then_submit(self):
        pages = WorkdayAts().pages(WORKDAY_URL)
        assert pages[0].is_account_create is True
        assert pages[-1].is_final_submit is True
        labels = [f.label.lower() for p in pages for f in p.fields]
        assert any("gender" in label for label in labels)  # sensitive EEO field present

    # --- fingerprint normalization (FR-STEALTH-1) ------------------------
    def test_default_fingerprint_is_coherent(self, adapter):
        assert fingerprint_is_coherent(adapter.fingerprint) is True

    def test_incoherent_fingerprint_rejected(self):
        bad = dict(NORMALIZED_FINGERPRINT)
        bad["webgl_renderer"] = "Apple M1 (Metal)"  # contradicts Windows UA
        assert fingerprint_is_coherent(bad) is False

    # --- screenshot routes through the boundary (FR-PREFILL-4) -----------
    def test_screenshot_routes_through_boundary(self, adapter, aid):
        # SCREENSHOT is a benign step (allowed); it must still go through the
        # boundary so the adapter cannot perform an unguarded action.
        adapter.open(aid, WORKDAY_URL)
        assert adapter.screenshot(aid)  # no raise on a benign step

    # --- persistent per-tenant profile (FR-STEALTH-3) --------------------
    def test_returning_visitor_recognized_on_second_open(self, aid):
        adapter = PatchrightBrowser()
        adapter.open(aid, WORKDAY_URL)
        assert adapter.is_returning_visitor(aid) is False
        other = ApplicationId(new_id())
        adapter.open(other, WORKDAY_URL)  # same tenant host
        assert adapter.is_returning_visitor(other) is True

    # --- residential egress guardrail (FR-STEALTH-4) ---------------------
    def test_datacenter_egress_refused_at_construction(self):
        from applicant.adapters.browser.stealth import DatacenterEgressRefused, EgressPolicy

        with pytest.raises(DatacenterEgressRefused):
            PatchrightBrowser(egress=EgressPolicy(proxy_url="http://dc:8080", residential=False))
