# -*- coding: utf-8 -*-
"""Hermetic unit tests for scripts/playtest_panels.py (the panel playtest harness).

Does NOT launch a browser — tests only importability, panel enumeration,
default path resolution, and the results contract shape.
"""

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
HARNESS_PATH = SCRIPTS_DIR / "playtest_panels.py"

# The webui panels dir
APPLICANT_WEBUI = PROJECT_ROOT / "a0-applicant" / "webui"

# Results schema keys a per-panel record MUST include
REQUIRED_RESULT_KEYS = {"rendered", "console_errors", "pageerrors", "http_5xx", "failed_requests", "unhandled_rejections", "ui_leaks", "blank_after_load", "dead_controls", "mobile_overflow", "mobile_offscreen", "mobile_screenshot", "a11y_no_name_controls", "a11y_images_no_alt", "a11y_inputs_no_label", "a11y_low_contrast_texts"}

# Error-injection result keys a per-panel record MUST include
REQUIRED_ERROR_INJECTION_KEYS = {"err_blank", "err_no_message", "err_leak", "console_errors", "pageerrors", "unhandled_rejections", "notes"}


class TestHarnessExists:
    """Verify the harness script is present and parseable."""

    def test_harness_file_exists(self):
        """scripts/playtest_panels.py exists as a regular file."""
        assert HARNESS_PATH.is_file(), f"Harness not found at {HARNESS_PATH}"

    def test_harness_is_parseable(self):
        """The file is syntactically valid Python."""
        source = HARNESS_PATH.read_text(encoding="utf-8")
        try:
            compile(source, str(HARNESS_PATH), "exec")
        except SyntaxError as exc:
            pytest.fail(f"Parse error: {exc}")

    def test_harness_imports_main_page_safely_without_playwright(self):
        """Importing the module should gracefully catch missing playwright."""
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "playtest_panels", str(HARNESS_PATH)
        )
        assert spec is not None, "Could not create module spec from harness"
        mod = importlib.util.module_from_spec(spec)
        sys.modules["playtest_panels"] = mod
        try:
            spec.loader.exec_module(mod)
        except ModuleNotFoundError as exc:
            if "playwright" in str(exc):
                pass  # Expected — playwright not installed in test venv
            else:
                pytest.fail(f"Unexpected import error: {exc}")
        finally:
            sys.modules.pop("playtest_panels", None)


class TestPanelEnumeration:
    """The harness correctly discovers applicant webui panels."""

    def test_webui_dir_exists(self):
        """The a0-applicant/webui/ directory exists."""
        assert APPLICANT_WEBUI.is_dir(), f"WebUI dir not found at {APPLICANT_WEBUI}"

    def test_enumerates_html_files(self):
        """webui/ contains at least one .html panel file."""
        html_files = list(APPLICANT_WEBUI.glob("*.html"))
        assert len(html_files) > 0, f"No .html files found in {APPLICANT_WEBUI}"

    def test_enumerates_health_panel(self):
        """The health.html panel exists as a baseline."""
        assert (APPLICANT_WEBUI / "health.html").is_file(), "health.html missing"

    def test_main_panel_exists(self):
        """The main.html panel exists as the primary entry point."""
        assert (APPLICANT_WEBUI / "main.html").is_file(), "main.html missing"


class TestResultsContract:
    """The harness's JSON output contract defines the required result shape."""

    RESULTS_SAMPLE_PATH = PROJECT_ROOT / "playtest-panels-results.json"

    @pytest.fixture
    def playtest_results(self):
        """Load the latest playtest results if available."""
        if not self.RESULTS_SAMPLE_PATH.is_file():
            pytest.skip("playtest-panels-results.json not found (run harness first)")
        with open(self.RESULTS_SAMPLE_PATH) as f:
            return json.load(f)

    def test_results_top_level_keys(self, playtest_results):
        """Results JSON has 'panels' and 'summary' keys."""
        assert "panels" in playtest_results, "Missing 'panels' key"
        assert isinstance(playtest_results["panels"], list), "'panels' must be a list"

    def test_every_panel_has_required_keys(self, playtest_results):
        """Every panel record includes rendered, console_errors, pageerrors, http_5xx, dead_controls."""
        for record in playtest_results["panels"]:
            missing = REQUIRED_RESULT_KEYS - set(record.keys())
            assert not missing, (
                f"Panel '{record.get('panel', '?')}' missing keys: {missing}"
            )

    def test_rendered_is_bool(self, playtest_results):
        """Every panel's 'rendered' field is a bool."""
        for record in playtest_results["panels"]:
            panel = record.get("panel", "?")
            assert isinstance(record["rendered"], bool), (
                f"Panel '{panel}' rendered is not bool: {record['rendered']}"
            )

    def test_error_fields_are_lists(self, playtest_results):
        """Error fields (console_errors, pageerrors, http_5xx, failed_requests, unhandled_rejections, ui_leaks, dead_controls) are lists."""
        list_fields = ["console_errors", "pageerrors", "http_5xx", "failed_requests", "unhandled_rejections", "ui_leaks", "dead_controls"]
        for record in playtest_results["panels"]:
            panel = record.get("panel", "?")
            for field in list_fields:
                val = record.get(field)
                assert isinstance(val, list), (
                    f"Panel '{panel}' {field} is not a list: {type(val).__name__}"
                )

    def test_blank_after_load_is_bool(self, playtest_results):
        """Every panel's 'blank_after_load' field is a bool."""
        for record in playtest_results["panels"]:
            panel = record.get("panel", "?")
            assert isinstance(record["blank_after_load"], bool), (
                f"Panel '{panel}' blank_after_load is not bool: {record['blank_after_load']}"
            )

    def test_mobile_overflow_is_bool(self, playtest_results):
        """Every panel's 'mobile_overflow' field is a bool."""
        for record in playtest_results["panels"]:
            panel = record.get("panel", "?")
            assert isinstance(record["mobile_overflow"], bool), (
                f"Panel '{panel}' mobile_overflow is not bool: {record['mobile_overflow']}"
            )

    def test_mobile_offscreen_is_list(self, playtest_results):
        """Every panel's 'mobile_offscreen' field is a list."""
        for record in playtest_results["panels"]:
            panel = record.get("panel", "?")
            assert isinstance(record["mobile_offscreen"], list), (
                f"Panel '{panel}' mobile_offscreen is not list: {record['mobile_offscreen']}"
            )

    def test_a11y_fields_are_lists(self, playtest_results):
        """A11y fields (a11y_no_name_controls, a11y_images_no_alt, a11y_inputs_no_label, a11y_low_contrast_texts) are lists."""
        a11y_fields = ["a11y_no_name_controls", "a11y_images_no_alt", "a11y_inputs_no_label", "a11y_low_contrast_texts"]
        for record in playtest_results["panels"]:
            panel = record.get("panel", "?")
            for field in a11y_fields:
                val = record.get(field)
                assert isinstance(val, list), (
                    f"Panel '{panel}' {field} is not a list: {type(val).__name__}"
                )

    def test_harness_source_references_a11y_keys(self):
        """The harness source references all a11y key names."""
        source = HARNESS_PATH.read_text(encoding="utf-8")
        a11y_keys = ["a11y_no_name_controls", "a11y_images_no_alt", "a11y_inputs_no_label", "a11y_low_contrast_texts"]
        for key in a11y_keys:
            assert key in source, f"Key '{key}' not mentioned in harness source"

    def test_harness_script_defines_results_contract(self):
        """The harness source references all contract keys."""
        source = HARNESS_PATH.read_text(encoding="utf-8")
        for key in REQUIRED_RESULT_KEYS:
            assert key in source, f"Key '{key}' not mentioned in harness source"


class TestHarnessConfig:
    """The harness has safe default configuration."""

    def test_shell_url_default(self):
        """SHELL_URL defaults to http://localhost:80."""
        source = HARNESS_PATH.read_text(encoding="utf-8")
        assert 'SHELL_URL = os.environ.get("SHELL_URL", "http://localhost:80")' in source

    def test_credentials_fallback(self):
        """Admin credentials fall back to env variables."""
        source = HARNESS_PATH.read_text(encoding="utf-8")
        assert "ADMIN_USER" in source
        assert "ADMIN_PW" in source or "ADMIN_PASSWORD" in source

    def test_uses_a0_dotenv(self):
        """Harness imports helpers.dotenv for resolving real credentials."""
        source = HARNESS_PATH.read_text(encoding="utf-8")
        assert "helpers" in source
        assert "dotenv" in source


class TestErrorInjectionContract:
    """The error-injection pass produces the correct result schema in the harness."""

    RESULTS_SAMPLE_PATH = PROJECT_ROOT / "playtest-panels-results.json"

    @pytest.fixture
    def playtest_results(self):
        """Load the latest playtest results if available."""
        if not self.RESULTS_SAMPLE_PATH.is_file():
            pytest.skip("playtest-panels-results.json not found (run harness first)")
        with open(self.RESULTS_SAMPLE_PATH) as f:
            data = json.load(f)
        if "error_injection" not in data:
            pytest.skip("error_injection key missing — results from old harness version")
        return data

    def test_harness_source_references_error_injection_keys(self):
        """The harness source references all required error-injection keys."""
        source = HARNESS_PATH.read_text(encoding="utf-8")
        for key in REQUIRED_ERROR_INJECTION_KEYS:
            assert key in source, f"Key '{key}' not mentioned in harness source"

    def test_results_has_error_injection_key(self, playtest_results):
        """Results JSON has 'error_injection' key."""
        assert "error_injection" in playtest_results, "Missing 'error_injection' key"
        assert isinstance(playtest_results["error_injection"], list), "'error_injection' must be a list"

    def test_every_error_injection_record_has_required_keys(self, playtest_results):
        """Every error-injection record has all required keys."""
        for record in playtest_results["error_injection"]:
            missing = REQUIRED_ERROR_INJECTION_KEYS - set(record.keys())
            assert not missing, (
                f"Panel '{record.get('panel', '?')}' missing error-injection keys: {missing}"
            )

    def test_err_blank_is_bool(self, playtest_results):
        """Every error-injection record's err_blank is a bool."""
        for record in playtest_results["error_injection"]:
            panel = record.get("panel", "?")
            assert isinstance(record["err_blank"], bool), (
                f"Panel '{panel}' err_blank is not bool: {record['err_blank']}"
            )

    def test_err_no_message_is_bool(self, playtest_results):
        """Every error-injection record's err_no_message is a bool."""
        for record in playtest_results["error_injection"]:
            panel = record.get("panel", "?")
            assert isinstance(record["err_no_message"], bool), (
                f"Panel '{panel}' err_no_message is not bool: {record['err_no_message']}"
            )

    def test_err_leak_is_bool(self, playtest_results):
        """Every error-injection record's err_leak is a bool."""
        for record in playtest_results["error_injection"]:
            panel = record.get("panel", "?")
            assert isinstance(record["err_leak"], bool), (
                f"Panel '{panel}' err_leak is not bool: {record['err_leak']}"
            )

    def test_error_injection_list_fields_are_lists(self, playtest_results):
        """Error-injection list fields (console_errors, pageerrors, unhandled_rejections, notes) are lists."""
        list_fields = ["console_errors", "pageerrors", "unhandled_rejections", "notes"]
        for record in playtest_results["error_injection"]:
            panel = record.get("panel", "?")
            for field in list_fields:
                val = record.get(field)
                assert isinstance(val, list), (
                    f"Panel '{panel}' {field} is not a list: {type(val).__name__}"
                )
