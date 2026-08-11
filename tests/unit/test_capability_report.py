import os
import importlib.util

import pytest

from applicant.app.capability_report import (
    Capability,
    REAL,
    STUB,
    _ok,
    build_capability_report,
    _orchestrator,
    report_as_dict,
    api_capability_report,
    LOAD_BEARING,
    _LABELS,
    _FIX_COPY,
    _ORDER,
)


@pytest.fixture(autouse=True)
def _no_cache():
    """xdist parallel safety: no caches to clear, but autouse keeps modules safe."""
    yield


class TestCapability:
    """Tests for the Capability frozen dataclass."""

    def test_construct_real(self):
        cap = Capability("browser", REAL, "ok (/usr/bin/chromium)")
        assert cap.name == "browser"
        assert cap.status == REAL
        assert cap.detail == "ok (/usr/bin/chromium)"
        assert cap.is_real is True

    def test_construct_stub(self):
        cap = Capability("postgres", STUB, "NOT REACHABLE (using in-memory storage)")
        assert cap.name == "postgres"
        assert cap.status == STUB
        assert cap.detail == "NOT REACHABLE (using in-memory storage)"
        assert cap.is_real is False

    def test_immutable(self):
        cap = Capability("browser", REAL, "ok")
        with pytest.raises((AttributeError, Exception)):
            cap.name = "postgres"  # type: ignore[misc]

    def test_equality(self):
        a = Capability("browser", REAL, "ok")
        b = Capability("browser", REAL, "ok")
        assert a == b

    def test_inequality(self):
        a = Capability("browser", REAL, "ok (/usr/bin/chromium)")
        b = Capability("browser", STUB, "disabled")
        assert a != b

    def test_hashable(self):
        caps = {
            Capability("browser", REAL, "ok"),
            Capability("postgres", STUB, "stub"),
        }
        assert len(caps) == 2

    def test_repr(self):
        cap = Capability("browser", REAL, "ok")
        r = repr(cap)
        assert "Capability" in r
        assert "browser" in r
        assert REAL in r

    def test_is_real_true(self):
        cap = Capability("orchestrator", REAL, "shim")
        assert cap.is_real is True

    def test_is_real_false(self):
        cap = Capability("orchestrator", STUB, "stub")
        assert cap.is_real is False


class TestOk:
    """Tests for the _ok helper."""

    def test_ok_lowercase(self):
        assert _ok("ok (connected)") is True

    def test_ok_capitalized(self):
        assert _ok("Ok (something)") is True

    def test_ok_all_caps(self):
        assert _ok("OK  (yes)") is True

    def test_ok_prefix_exact(self):
        assert _ok("okay but not really") is True

    def test_not_found(self):
        assert _ok("NOT FOUND (not installed)") is False

    def test_disabled(self):
        assert _ok("disabled (BROWSER_REAL not set)") is False

    def test_degraded(self):
        assert _ok("DEGRADED (missing Writer)") is False

    def test_empty_string(self):
        assert _ok("") is False

    def test_none_raises(self):
        with pytest.raises(AttributeError):
            _ok(None)  # type: ignore[arg-type]


class TestBuildCapabilityReport:
    """Tests for build_capability_report with mocked capability_status."""

    def test_all_real(self, monkeypatch):
        def fake_status(*, browser_real=True, postgres_engine=None):
            return {
                "tex": "ok (/usr/bin/lualatex)",
                "libreoffice": "ok (/usr/bin/soffice)",
                "fc_cache": "ok (/usr/bin/fc-cache)",
                "browser": "ok (/usr/bin/camoufox)",
                "postgres": "ok (connected)",
            }

        monkeypatch.setattr(
            "applicant.app.capability_report.capability_status", fake_status
        )
        monkeypatch.setenv("ORCHESTRATOR_BACKEND", "shim")

        report = build_capability_report(browser_real=True, postgres_engine=object())
        assert "postgres" in report
        assert "resume_renderer" in report
        assert "browser" in report
        assert "orchestrator" in report
        assert report["postgres"].is_real is True
        assert report["resume_renderer"].is_real is True
        assert report["browser"].is_real is True
        assert report["orchestrator"].is_real is True

    def test_all_stub(self, monkeypatch):
        def fake_status(*, browser_real=True, postgres_engine=None):
            return {
                "tex": "NOT FOUND (no lualatex)",
                "libreoffice": "NOT FOUND (no soffice)",
                "fc_cache": "NOT FOUND (no fc-cache)",
                "browser": "NOT FOUND (BROWSER_REAL=true but no binary)",
                "postgres": "NOT REACHABLE (using in-memory storage)",
            }

        monkeypatch.setattr(
            "applicant.app.capability_report.capability_status", fake_status
        )
        monkeypatch.setenv("ORCHESTRATOR_BACKEND", "shim")

        report = build_capability_report(browser_real=True, postgres_engine=None)
        assert report["postgres"].is_real is False
        assert report["resume_renderer"].is_real is False
        assert report["browser"].is_real is False
        assert report["orchestrator"].is_real is True  # shim always real

    def test_resume_renderer_tex_only(self, monkeypatch):
        def fake_status(*, browser_real=True, postgres_engine=None):
            return {
                "tex": "ok (/usr/bin/lualatex)",
                "libreoffice": "NOT FOUND (no soffice)",
                "fc_cache": "NOT FOUND",
                "browser": "disabled",
                "postgres": "NOT REACHABLE",
            }

        monkeypatch.setattr(
            "applicant.app.capability_report.capability_status", fake_status
        )
        report = build_capability_report(browser_real=False, postgres_engine=None)
        cap = report["resume_renderer"]
        assert cap.is_real is True
        assert "lualatex" in cap.detail
        assert "libreoffice" not in cap.detail

    def test_resume_renderer_libreoffice_only(self, monkeypatch):
        def fake_status(*, browser_real=True, postgres_engine=None):
            return {
                "tex": "NOT FOUND (no lualatex)",
                "libreoffice": "ok (/usr/bin/soffice)",
                "fc_cache": "NOT FOUND",
                "browser": "disabled",
                "postgres": "NOT REACHABLE",
            }

        monkeypatch.setattr(
            "applicant.app.capability_report.capability_status", fake_status
        )
        report = build_capability_report(browser_real=False, postgres_engine=None)
        cap = report["resume_renderer"]
        assert cap.is_real is True
        assert "soffice" in cap.detail
        assert "lualatex" not in cap.detail

    def test_resume_renderer_both(self, monkeypatch):
        def fake_status(*, browser_real=True, postgres_engine=None):
            return {
                "tex": "ok (/usr/bin/xelatex)",
                "libreoffice": "ok (/usr/bin/soffice)",
                "fc_cache": "NOT FOUND",
                "browser": "disabled",
                "postgres": "NOT REACHABLE",
            }

        monkeypatch.setattr(
            "applicant.app.capability_report.capability_status", fake_status
        )
        report = build_capability_report(browser_real=False, postgres_engine=None)
        cap = report["resume_renderer"]
        assert cap.is_real is True
        assert "xelatex" in cap.detail
        assert "soffice" in cap.detail

    def test_resume_renderer_neither(self, monkeypatch):
        def fake_status(*, browser_real=True, postgres_engine=None):
            return {
                "tex": "NOT FOUND (no tex)",
                "libreoffice": "NOT FOUND (no soffice)",
                "fc_cache": "NOT FOUND",
                "browser": "disabled",
                "postgres": "NOT REACHABLE",
            }

        monkeypatch.setattr(
            "applicant.app.capability_report.capability_status", fake_status
        )
        report = build_capability_report(browser_real=False, postgres_engine=None)
        cap = report["resume_renderer"]
        assert cap.is_real is False
        assert "stub" in cap.detail.lower()

    def test_passes_browser_real_flag_false(self, monkeypatch):
        captured_kwargs = {}

        def fake_status(**kwargs):
            captured_kwargs.update(kwargs)
            return {
                "tex": "NOT FOUND",
                "libreoffice": "NOT FOUND",
                "fc_cache": "NOT FOUND",
                "browser": "disabled",
                "postgres": "NOT REACHABLE",
            }

        monkeypatch.setattr(
            "applicant.app.capability_report.capability_status", fake_status
        )
        build_capability_report(browser_real=False, postgres_engine=None)
        assert captured_kwargs.get("browser_real") is False
        assert captured_kwargs.get("postgres_engine") is None

    def test_passes_browser_real_flag_true(self, monkeypatch):
        captured_kwargs = {}

        def fake_status(**kwargs):
            captured_kwargs.update(kwargs)
            return {
                "tex": "NOT FOUND",
                "libreoffice": "NOT FOUND",
                "fc_cache": "NOT FOUND",
                "browser": "ok (binary)",
                "postgres": "ok (connected)",
            }

        monkeypatch.setattr(
            "applicant.app.capability_report.capability_status", fake_status
        )
        engine = object()
        build_capability_report(browser_real=True, postgres_engine=engine)
        assert captured_kwargs.get("browser_real") is True
        assert captured_kwargs.get("postgres_engine") is engine


class TestOrchestrator:
    """Tests for _orchestrator (+ mocking os.environ / importlib)."""

    def test_default_shim(self, monkeypatch):
        monkeypatch.delenv("ORCHESTRATOR_BACKEND", raising=False)
        cap = _orchestrator()
        assert cap.name == "orchestrator"
        assert cap.is_real is True
        assert "shim" in cap.detail

    def test_explicit_shim(self, monkeypatch):
        monkeypatch.setenv("ORCHESTRATOR_BACKEND", "shim")
        cap = _orchestrator()
        assert cap.is_real is True
        assert "shim" in cap.detail

    def test_shim_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("ORCHESTRATOR_BACKEND", "SHIM")
        cap = _orchestrator()
        assert cap.is_real is True
        assert "shim" in cap.detail

    def test_shim_with_whitespace(self, monkeypatch):
        monkeypatch.setenv("ORCHESTRATOR_BACKEND", "  shim  ")
        cap = _orchestrator()
        assert cap.is_real is True
        assert "shim" in cap.detail

    def test_dbos_installed(self, monkeypatch):
        monkeypatch.setenv("ORCHESTRATOR_BACKEND", "dbos")

        def fake_find_spec(name, *args, **kwargs):
            if name == "dbos":
                return object()  # truthy = found
            return None

        monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)
        cap = _orchestrator()
        assert cap.is_real is True
        assert "dbos" in cap.detail

    def test_dbos_not_installed(self, monkeypatch):
        monkeypatch.setenv("ORCHESTRATOR_BACKEND", "dbos")

        def fake_find_spec(name, *args, **kwargs):
            if name == "dbos":
                return None
            return None

        monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)
        cap = _orchestrator()
        assert cap.is_real is False
        assert "not installed" in cap.detail

    def test_unknown_backend_falls_through(self, monkeypatch):
        monkeypatch.setenv("ORCHESTRATOR_BACKEND", "magical")
        cap = _orchestrator()
        # Falls through to the STUB return
        assert cap.is_real is False
        assert cap.name == "orchestrator"


class TestReportAsDict:
    """Tests for the report_as_dict convenience flattening."""

    def test_shape_all_real(self, monkeypatch):
        def fake_status(*, browser_real=True, postgres_engine=None):
            return {
                "tex": "ok (/usr/bin/xelatex)",
                "libreoffice": "ok (/usr/bin/soffice)",
                "fc_cache": "ok",
                "browser": "ok (/usr/bin/chrome)",
                "postgres": "ok (connected)",
            }

        monkeypatch.setattr(
            "applicant.app.capability_report.capability_status", fake_status
        )
        monkeypatch.setenv("ORCHESTRATOR_BACKEND", "shim")

        flat = report_as_dict(browser_real=True, postgres_engine=object())
        for name in ("postgres", "resume_renderer", "browser", "orchestrator"):
            assert name in flat
            assert "status" in flat[name]
            assert "detail" in flat[name]
            assert flat[name]["status"] == REAL

    def test_shape_mixed(self, monkeypatch):
        def fake_status(*, browser_real=True, postgres_engine=None):
            return {
                "tex": "NOT FOUND",
                "libreoffice": "NOT FOUND",
                "fc_cache": "NOT FOUND",
                "browser": "ok (binary)",
                "postgres": "NOT REACHABLE (in-memory)",
            }

        monkeypatch.setattr(
            "applicant.app.capability_report.capability_status", fake_status
        )
        monkeypatch.setenv("ORCHESTRATOR_BACKEND", "shim")

        flat = report_as_dict(browser_real=True, postgres_engine=None)
        assert flat["postgres"]["status"] == STUB
        assert flat["resume_renderer"]["status"] == STUB
        assert flat["browser"]["status"] == REAL
        assert flat["orchestrator"]["status"] == REAL


class TestApiCapabilityReport:
    """Tests for api_capability_report (P1-3 health-panel shape)."""

    def test_returns_correct_keys(self, monkeypatch):
        def fake_status(*, browser_real=True, postgres_engine=None):
            return {
                "tex": "NOT FOUND",
                "libreoffice": "NOT FOUND",
                "fc_cache": "NOT FOUND",
                "browser": "NOT FOUND",
                "postgres": "NOT REACHABLE",
            }

        monkeypatch.setattr(
            "applicant.app.capability_report.capability_status", fake_status
        )
        monkeypatch.setenv("ORCHESTRATOR_BACKEND", "shim")

        result = api_capability_report()
        assert "capabilities" in result
        assert "degraded" in result
        assert "load_bearing_degraded" in result
        assert "all_real" in result

    def test_all_real_flag(self, monkeypatch):
        def fake_status(*, browser_real=True, postgres_engine=None):
            return {
                "tex": "ok (xelatex)",
                "libreoffice": "ok (soffice)",
                "fc_cache": "ok",
                "browser": "ok (chrome)",
                "postgres": "ok (connected)",
            }

        monkeypatch.setattr(
            "applicant.app.capability_report.capability_status", fake_status
        )
        monkeypatch.setenv("ORCHESTRATOR_BACKEND", "shim")

        result = api_capability_report(browser_real=True, postgres_engine=object())
        assert result["all_real"] is True
        assert result["degraded"] == []
        assert result["load_bearing_degraded"] == []

    def test_mixed_stubs(self, monkeypatch):
        def fake_status(*, browser_real=True, postgres_engine=None):
            return {
                "tex": "NOT FOUND",
                "libreoffice": "NOT FOUND",
                "fc_cache": "NOT FOUND",
                "browser": "ok (chrome)",
                "postgres": "NOT REACHABLE",
            }

        monkeypatch.setattr(
            "applicant.app.capability_report.capability_status", fake_status
        )
        monkeypatch.setenv("ORCHESTRATOR_BACKEND", "shim")

        result = api_capability_report(browser_real=True)
        assert result["all_real"] is False
        assert "postgres" in result["degraded"]
        assert "resume_renderer" in result["degraded"]
        assert "postgres" in result["load_bearing_degraded"]
        assert "resume_renderer" in result["load_bearing_degraded"]
        assert "browser" not in result["degraded"]

    def test_ordering(self, monkeypatch):
        def fake_status(*, browser_real=True, postgres_engine=None):
            return {
                "tex": "NOT FOUND",
                "libreoffice": "NOT FOUND",
                "fc_cache": "NOT FOUND",
                "browser": "NOT FOUND",
                "postgres": "NOT REACHABLE",
            }

        monkeypatch.setattr(
            "applicant.app.capability_report.capability_status", fake_status
        )
        monkeypatch.setenv("ORCHESTRATOR_BACKEND", "shim")

        result = api_capability_report()
        caps = result["capabilities"]
        names = [c["name"] for c in caps]
        assert names == ["postgres", "resume_renderer", "browser", "orchestrator"]

    def test_each_item_shape(self, monkeypatch):
        def fake_status(*, browser_real=True, postgres_engine=None):
            return {
                "tex": "NOT FOUND",
                "libreoffice": "NOT FOUND",
                "fc_cache": "NOT FOUND",
                "browser": "ok (binary)",
                "postgres": "NOT REACHABLE",
            }

        monkeypatch.setattr(
            "applicant.app.capability_report.capability_status", fake_status
        )
        monkeypatch.setenv("ORCHESTRATOR_BACKEND", "shim")

        result = api_capability_report()
        caps = result["capabilities"]
        for item in caps:
            assert "name" in item
            assert "label" in item
            assert "status" in item
            assert "detail" in item
            assert "load_bearing" in item
            assert "fix" in item

    def test_fix_only_when_stub(self, monkeypatch):
        def fake_status(*, browser_real=True, postgres_engine=None):
            return {
                "tex": "ok (xelatex)",
                "libreoffice": "ok (soffice)",
                "fc_cache": "ok",
                "browser": "ok (chrome)",
                "postgres": "NOT REACHABLE",
            }

        monkeypatch.setattr(
            "applicant.app.capability_report.capability_status", fake_status
        )
        monkeypatch.setenv("ORCHESTRATOR_BACKEND", "shim")

        result = api_capability_report()
        caps_by_name = {c["name"]: c for c in result["capabilities"]}
        assert caps_by_name["postgres"]["fix"] != ""
        assert caps_by_name["resume_renderer"]["fix"] == ""
        assert caps_by_name["browser"]["fix"] == ""
        assert caps_by_name["orchestrator"]["fix"] == ""

    def test_load_bearing_sets(self, monkeypatch):
        def fake_status(*, browser_real=True, postgres_engine=None):
            return {
                "tex": "NOT FOUND",
                "libreoffice": "NOT FOUND",
                "fc_cache": "NOT FOUND",
                "browser": "NOT FOUND",
                "postgres": "NOT REACHABLE",
            }

        monkeypatch.setattr(
            "applicant.app.capability_report.capability_status", fake_status
        )
        monkeypatch.setenv("ORCHESTRATOR_BACKEND", "shim")

        result = api_capability_report()
        caps_by_name = {c["name"]: c for c in result["capabilities"]}
        assert caps_by_name["postgres"]["load_bearing"] is True
        assert caps_by_name["resume_renderer"]["load_bearing"] is True
        assert caps_by_name["browser"]["load_bearing"] is True
        assert caps_by_name["orchestrator"]["load_bearing"] is False

    def test_labels_match(self, monkeypatch):
        def fake_status(*, browser_real=True, postgres_engine=None):
            return {
                "tex": "NOT FOUND",
                "libreoffice": "NOT FOUND",
                "fc_cache": "NOT FOUND",
                "browser": "NOT FOUND",
                "postgres": "NOT REACHABLE",
            }

        monkeypatch.setattr(
            "applicant.app.capability_report.capability_status", fake_status
        )
        monkeypatch.setenv("ORCHESTRATOR_BACKEND", "shim")

        result = api_capability_report()
        for c in result["capabilities"]:
            assert c["label"] == _LABELS[c["name"]]


class TestConstants:
    """Verify module-level constants are as expected."""

    def test_order_well_defined(self):
        assert len(_ORDER) == 4
        assert _ORDER == ("postgres", "resume_renderer", "browser", "orchestrator")

    def test_load_bearing_set(self):
        assert LOAD_BEARING == frozenset({"postgres", "resume_renderer", "browser"})
        assert "orchestrator" not in LOAD_BEARING

    def test_labels_exist_for_all_capabilities(self):
        for name in _ORDER:
            assert name in _LABELS

    def test_fix_copy_exists_for_all_capabilities(self):
        for name in _ORDER:
            assert name in _FIX_COPY
