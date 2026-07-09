"""P1-3 (issue #655) — the honest health panel's engine surface.

``GET /api/health/capabilities`` exposes the pre-existing #188 boot-time
capability self-report (``app/capability_report.py``) over HTTP: postgres,
résumé renderer, browser, orchestrator, each real-vs-stub with a plain-
language label and actionable fix copy — never a bare status dot, and never
silent about which items are load-bearing for the autonomous loop.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from applicant.app.capability_report import (
    LOAD_BEARING,
    STUB,
    api_capability_report,
    build_capability_report,
)
from applicant.app.main import create_app


class TestBuildCapabilityReportIncludesPostgres:
    def test_report_now_includes_postgres_alongside_the_existing_three(self):
        # #188's original acceptance criterion only named resume_renderer/
        # browser/orchestrator; P1-3's DoR also names postgres — added without
        # dropping any existing key (subset check mirrors the #188 BDD step).
        report = build_capability_report()
        keys = {str(k).lower() for k in report}
        assert {"postgres", "resume_renderer", "browser", "orchestrator"} <= keys

    def test_postgres_stub_when_no_engine(self):
        report = build_capability_report(postgres_engine=None)
        assert report["postgres"].status == STUB
        assert "in-memory" in report["postgres"].detail.lower()

    def test_postgres_real_when_engine_present(self):
        report = build_capability_report(postgres_engine=object())
        assert report["postgres"].status != STUB


class TestApiCapabilityReportShape:
    def test_returns_all_four_capabilities_in_dor_order(self):
        out = api_capability_report(browser_real=False, postgres_engine=None)
        names = [c["name"] for c in out["capabilities"]]
        assert names == ["postgres", "resume_renderer", "browser", "orchestrator"]

    def test_every_capability_has_label_status_detail_load_bearing_fix(self):
        out = api_capability_report(browser_real=False, postgres_engine=None)
        for cap in out["capabilities"]:
            assert cap["label"], f"{cap['name']} must have a plain-language label"
            assert cap["status"] in ("real", "stub")
            assert isinstance(cap["detail"], str) and cap["detail"]
            assert isinstance(cap["load_bearing"], bool)
            assert isinstance(cap["fix"], str)

    def test_degraded_items_carry_actionable_fix_copy_not_a_bare_dot(self):
        # Hermetic boot: no Postgres, no TeX/LibreOffice, browser disabled —
        # postgres/resume_renderer/browser are all stub here.
        out = api_capability_report(browser_real=False, postgres_engine=None)
        for cap in out["capabilities"]:
            if cap["status"] == STUB:
                assert cap["fix"], f"{cap['name']} degraded with no fix copy"
                # Fix copy must be a real sentence, not a placeholder.
                assert len(cap["fix"]) > 20

    def test_real_items_carry_no_fix_copy(self):
        out = api_capability_report(browser_real=False, postgres_engine=object())
        for cap in out["capabilities"]:
            if cap["status"] == "real":
                assert cap["fix"] == ""

    def test_degraded_and_load_bearing_degraded_lists_are_consistent(self):
        out = api_capability_report(browser_real=False, postgres_engine=None)
        assert set(out["load_bearing_degraded"]) <= set(out["degraded"])
        assert set(out["load_bearing_degraded"]) == set(out["degraded"]) & LOAD_BEARING

    def test_all_real_true_only_when_nothing_degraded(self):
        degraded = api_capability_report(browser_real=False, postgres_engine=None)
        assert degraded["all_real"] is False
        assert degraded["degraded"]

    def test_orchestrator_shim_is_not_load_bearing(self):
        # The default shim is always real and already durable across restarts;
        # only an explicit, missing dbos opt-in would ever stub it, and even
        # then the search still runs — so it must not gate the Today banner.
        assert "orchestrator" not in LOAD_BEARING

    def test_postgres_resume_browser_are_load_bearing(self):
        assert {"postgres", "resume_renderer", "browser"} <= LOAD_BEARING


class TestHealthCapabilitiesEndpoint:
    def test_endpoint_reachable_without_any_setup_gate(self):
        # Ungated: ``/api/health/capabilities`` must answer even before an LLM
        # is configured — that's the whole point (surfacing WHY automated work
        # hasn't started).
        app = create_app()
        with TestClient(app) as c:
            res = c.get("/api/health/capabilities")
        assert res.status_code == 200

    def test_response_has_generated_at_and_the_capability_report_shape(self):
        app = create_app()
        with TestClient(app) as c:
            res = c.get("/api/health/capabilities")
        body = res.json()
        assert "generated_at" in body and body["generated_at"]
        assert isinstance(body["capabilities"], list) and len(body["capabilities"]) == 4
        assert isinstance(body["degraded"], list)
        assert isinstance(body["load_bearing_degraded"], list)
        assert isinstance(body["all_real"], bool)

    def test_response_carries_the_running_engine_version(self):
        # P3-5 (release engineering): the same applicant.version.__version__
        # the FastAPI app advertises, so it's reachable through the front-door
        # health panel proxy — not just an internal-only /healthz field.
        from applicant.version import __version__

        app = create_app()
        with TestClient(app) as c:
            res = c.get("/api/health/capabilities")
        body = res.json()
        assert body["version"] == __version__

    def test_hermetic_boot_reports_postgres_degraded_honestly(self):
        # The hermetic test lane has no Postgres — the endpoint must say so
        # rather than rendering a false-green check (H-series honesty).
        app = create_app()
        with TestClient(app) as c:
            res = c.get("/api/health/capabilities")
        body = res.json()
        postgres = next(c for c in body["capabilities"] if c["name"] == "postgres")
        assert postgres["status"] == "stub"
        assert postgres["fix"]
