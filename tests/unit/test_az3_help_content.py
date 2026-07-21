"""AZ3 (#845) Slice A — unit tests for the help content model, proxy, and panel.

Hermetic: reads config yaml and source-asserts proxy/panel structure without
importing the API handler (which depends on flask in the venv-a0 runtime).
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

# --- Paths ---------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[2]
HELP_YAML = ROOT / "a0-applicant" / "config" / "help_content.yaml"
HELP_PY = ROOT / "a0-applicant" / "api" / "help.py"
HELP_HTML = ROOT / "a0-applicant" / "webui" / "help.html"

# Every surface listed in the spec
EXPECTED_SURFACES = {
    "today", "digest", "documents", "campaigns", "channels", "tracker",
    "discovery", "criteria", "screening", "vault", "easy_apply",
    "gallery", "compare", "mind", "notifications", "health",
    "ops", "fonts", "model_endpoints", "feedback", "chat",
    "activity", "takeover", "tiers",
    "privacy", "savejob",
    "demo",
    "automation",
    "shortcuts",
    "config",
    "interview_prep",
}

# Spec-jargon tokens that must NOT appear in help copy
FORBIDDEN_TOKENS = ["AZ3", "H5", "proxy", "lens", "DoD"]


# === D4(a): Validate help_content.yaml ===================================

class TestHelpContentYaml:
    """Verify the single source of truth is complete and jargon-free."""

    @pytest.fixture(autouse=True)
    def _load_yaml(self) -> None:
        assert HELP_YAML.is_file(), f"help_content.yaml not found at {HELP_YAML}"
        with open(HELP_YAML, "r", encoding="utf-8") as f:
            self.content = yaml.safe_load(f)
        assert isinstance(self.content, dict), "help_content.yaml did not parse to a dict"

    def test_all_expected_surfaces_present(self) -> None:
        actual = set(self.content.keys())
        missing = EXPECTED_SURFACES - actual
        extra = actual - EXPECTED_SURFACES
        assert not missing, f"Missing surfaces: {sorted(missing)}"
        assert not extra, f"Unexpected surfaces: {sorted(extra)}"
        assert len(self.content) == len(EXPECTED_SURFACES)

    def test_every_surface_has_valid_fields(self) -> None:
        for sid, s in self.content.items():
            assert isinstance(s, dict), f"{sid}: value is not a dict"
            assert "title" in s, f"{sid}: missing 'title'"
            assert isinstance(s["title"], str) and len(s["title"]) > 0, f"{sid}: title is empty"
            assert "steps" in s, f"{sid}: missing 'steps'"
            steps = s["steps"]
            assert isinstance(steps, list), f"{sid}: steps is not a list"
            assert len(steps) >= 3, f"{sid}: has {len(steps)} steps, need >= 3"
            assert "prerequisites" in s, f"{sid}: missing 'prerequisites'"
            assert isinstance(s["prerequisites"], str), f"{sid}: prerequisites is not a string"

    def test_no_spec_jargon_in_copy(self) -> None:
        yaml_text = HELP_YAML.read_text(encoding="utf-8")
        for token in FORBIDDEN_TOKENS:
            assert token not in yaml_text, f"Forbidden token '{token}' found in help_content.yaml"


# === D4(b): Source-assert help.py dispatch ===============================

class TestHelpPyDispatch:
    """Verify help.py dispatch handles list/get/unknown without importing it."""

    def test_help_py_exists(self) -> None:
        assert HELP_PY.is_file(), f"help.py not found at {HELP_PY}"

    def test_has_dispatch_function(self) -> None:
        source = HELP_PY.read_text(encoding="utf-8")
        assert "def dispatch(input: dict) -> dict:" in source
        assert "if action == \"list\":" in source
        assert "if action == \"get\":" in source

    def test_unknown_action_returns_400(self) -> None:
        source = HELP_PY.read_text(encoding="utf-8")
        assert "return {\"ok\": False, \"status\": 400, \"error\":" in source
        # The pattern is at the end of dispatch, after the get branch
        assert "unknown help action" in source

    def test_has_apihandler_class(self) -> None:
        source = HELP_PY.read_text(encoding="utf-8")
        assert "class Help(ApiHandler):" in source
        assert "async def process(self, input: dict, request: Request) -> dict:" in source
        assert "return dispatch(input)" in source

    def test_uses_yaml_config(self) -> None:
        source = HELP_PY.read_text(encoding="utf-8")
        assert "help_content.yaml" in source
        assert "yaml.safe_load" in source


# === D4(c): Source-assert help.html ======================================

class TestHelpHtmlPanel:
    """Verify help.html renders from the proxy with proper error handling."""

    def test_help_html_exists(self) -> None:
        assert HELP_HTML.is_file(), f"help.html not found at {HELP_HTML}"

    def test_calls_list_action(self) -> None:
        source = HELP_HTML.read_text(encoding="utf-8")
        assert "callJsonApi('help'" in source or 'callJsonApi("help"' in source
        assert "action: 'list'" in source or 'action: "list"' in source

    def test_calls_get_action(self) -> None:
        source = HELP_HTML.read_text(encoding="utf-8")
        assert "action: 'get'" in source or 'action: "get"' in source
        assert "surface:" in source

    def test_has_error_handling(self) -> None:
        source = HELP_HTML.read_text(encoding="utf-8")
        assert "error" in source.lower()
        assert "!r.ok" in source or 'r.ok' in source

    def test_has_loading_state(self) -> None:
        source = HELP_HTML.read_text(encoding="utf-8")
        assert "loading" in source.lower()

    def test_has_empty_state(self) -> None:
        source = HELP_HTML.read_text(encoding="utf-8")
        assert "No help content" in source or "empty" in source.lower()

    def test_has_alpine_js_data(self) -> None:
        source = HELP_HTML.read_text(encoding="utf-8")
        assert "window.Alpine.data('ahelp'" in source or "x-data" in source

    def test_expandable_surfaces(self) -> None:
        source = HELP_HTML.read_text(encoding="utf-8")
        # Must use x-for to iterate over surfaces from proxy
        assert "x-for" in source
        assert "surface-header" in source

    def test_prerequisites_displayed(self) -> None:
        source = HELP_HTML.read_text(encoding="utf-8")
        assert "prerequisites" in source.lower()


# === D4(d): Internal collection check ====================================

def test_module_collects_at_least_one() -> None:
    """Meta: this test file must collect > 0 tests."""
    assert True, "Sanity check: the test module must exist."
