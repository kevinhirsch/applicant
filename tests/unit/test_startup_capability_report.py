"""#188 — Startup capability report: REAL vs stub detection.

The engine degrades silently when optional binaries/services are absent. This
suite verifies that:

1. ``capability_status()`` returns the expected keys for every optional capability.
2. When a binary is absent (``shutil.which`` patched to None) the status string
   contains "NOT FOUND".
3. When a binary IS present the status string starts with "ok".
4. The ``/healthz`` response body includes a ``capabilities`` sub-dict.
5. The ``browser_real=False`` path always reports "disabled" regardless of
   which browser binaries happen to be on PATH.
6. The ``postgres_engine=None`` path reports the in-memory sentinel.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

import applicant.observability.capabilities as cap_mod
from applicant.app.main import create_app
from applicant.observability.capabilities import capability_status

# ---------------------------------------------------------------------------
# capability_status() unit tests
# ---------------------------------------------------------------------------


class TestCapabilityStatusKeys:
    def test_returns_all_expected_keys(self):
        status = capability_status(browser_real=False, postgres_engine=None)
        assert set(status.keys()) == {"tex", "libreoffice", "fc_cache", "browser", "postgres"}

    def test_all_values_are_strings(self):
        status = capability_status(browser_real=False, postgres_engine=None)
        for key, val in status.items():
            assert isinstance(val, str), f"{key!r} value should be a string, got {type(val)}"


class TestTexStatus:
    def test_tex_not_found_when_binary_absent(self, monkeypatch):
        monkeypatch.setattr(cap_mod.shutil, "which", lambda name: None)
        status = capability_status(browser_real=False, postgres_engine=None)
        assert "NOT FOUND" in status["tex"]

    def test_tex_ok_when_lualatex_present(self, monkeypatch):
        monkeypatch.setattr(
            cap_mod.shutil, "which",
            lambda name: "/usr/bin/lualatex" if name == "lualatex" else None,
        )
        status = capability_status(browser_real=False, postgres_engine=None)
        assert status["tex"].startswith("ok")
        assert "lualatex" in status["tex"]

    def test_tex_ok_when_xelatex_present(self, monkeypatch):
        monkeypatch.setattr(
            cap_mod.shutil, "which",
            lambda name: "/usr/bin/xelatex" if name == "xelatex" else None,
        )
        status = capability_status(browser_real=False, postgres_engine=None)
        assert status["tex"].startswith("ok")
        assert "xelatex" in status["tex"]


class TestLibreOfficeStatus:
    def test_libreoffice_not_found_when_binary_absent(self, monkeypatch):
        monkeypatch.setattr(cap_mod.shutil, "which", lambda name: None)
        status = capability_status(browser_real=False, postgres_engine=None)
        assert "NOT FOUND" in status["libreoffice"]

    def test_libreoffice_ok_when_soffice_present(self, monkeypatch):
        monkeypatch.setattr(
            cap_mod.shutil, "which",
            lambda name: "/usr/bin/soffice" if name == "soffice" else None,
        )
        status = capability_status(browser_real=False, postgres_engine=None)
        assert status["libreoffice"].startswith("ok")
        assert "soffice" in status["libreoffice"]


class TestFcCacheStatus:
    def test_fc_cache_not_found_when_absent(self, monkeypatch):
        monkeypatch.setattr(cap_mod.shutil, "which", lambda name: None)
        status = capability_status(browser_real=False, postgres_engine=None)
        assert "NOT FOUND" in status["fc_cache"]

    def test_fc_cache_ok_when_present(self, monkeypatch):
        monkeypatch.setattr(
            cap_mod.shutil, "which",
            lambda name: "/usr/bin/fc-cache" if name == "fc-cache" else None,
        )
        status = capability_status(browser_real=False, postgres_engine=None)
        assert status["fc_cache"].startswith("ok")


class TestBrowserStatus:
    def test_browser_disabled_when_browser_real_false(self, monkeypatch):
        # Even if a chrome binary is on PATH, browser_real=False → "disabled"
        monkeypatch.setattr(
            cap_mod.shutil, "which",
            lambda name: "/usr/bin/google-chrome" if name == "google-chrome" else None,
        )
        status = capability_status(browser_real=False, postgres_engine=None)
        assert "disabled" in status["browser"]

    def test_browser_not_found_when_real_but_no_binary(self, monkeypatch):
        monkeypatch.setattr(cap_mod.shutil, "which", lambda name: None)
        status = capability_status(browser_real=True, postgres_engine=None)
        assert "NOT FOUND" in status["browser"]

    def test_browser_ok_when_real_and_chrome_present(self, monkeypatch):
        monkeypatch.setattr(
            cap_mod.shutil, "which",
            lambda name: "/usr/bin/google-chrome" if name == "google-chrome" else None,
        )
        status = capability_status(browser_real=True, postgres_engine=None)
        assert status["browser"].startswith("ok")

    def test_browser_ok_when_real_and_camoufox_present(self, monkeypatch):
        monkeypatch.setattr(
            cap_mod.shutil, "which",
            lambda name: "/usr/local/bin/camoufox" if name == "camoufox" else None,
        )
        status = capability_status(browser_real=True, postgres_engine=None)
        assert status["browser"].startswith("ok")
        assert "camoufox" in status["browser"]


class TestPostgresStatus:
    def test_postgres_not_reachable_when_engine_is_none(self):
        status = capability_status(browser_real=False, postgres_engine=None)
        assert "NOT REACHABLE" in status["postgres"]
        assert "in-memory" in status["postgres"]

    def test_postgres_ok_when_engine_present(self):
        sentinel = object()
        status = capability_status(browser_real=False, postgres_engine=sentinel)
        assert status["postgres"].startswith("ok")


# ---------------------------------------------------------------------------
# /healthz includes capabilities sub-dict
# ---------------------------------------------------------------------------


class TestHealthzCapabilities:
    def test_healthz_includes_capabilities_key(self):
        app = create_app()
        with TestClient(app) as c:
            res = c.get("/healthz")
        assert res.status_code == 200
        body = res.json()
        assert "capabilities" in body["checks"], (
            "/healthz checks must include a 'capabilities' sub-dict"
        )

    def test_healthz_capabilities_has_all_expected_keys(self):
        app = create_app()
        with TestClient(app) as c:
            res = c.get("/healthz")
        caps = res.json()["checks"]["capabilities"]
        assert set(caps.keys()) >= {"tex", "libreoffice", "fc_cache", "browser", "postgres"}

    def test_healthz_postgres_in_memory_on_hermetic_boot(self):
        # The hermetic test lane has no Postgres, so postgres capability is "NOT REACHABLE".
        app = create_app()
        with TestClient(app) as c:
            res = c.get("/healthz")
        caps = res.json()["checks"]["capabilities"]
        assert "NOT REACHABLE" in caps["postgres"]
