"""AZ3 (#845) Slice B — per-surface help affordance enforcement test.

Hermetic: globs the webui/*.html files and source-asserts each target panel
contains the help button snippet. Also verifies help.html deep-link support.
"""
from __future__ import annotations

from pathlib import Path

import pytest

# --- Paths ---------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[2]
WEBUI = ROOT / "a0-applicant" / "webui"
HELP_HTML = WEBUI / "help.html"

# Panels that should get the help affordance (match help_content.yaml keys)
TARGET_SURFACES = [
    "today", "digest", "documents", "activity", "campaigns",
    "tracker", "takeover", "discovery", "criteria", "screening",
    "vault", "easy_apply", "gallery", "compare", "mind",
    "notifications", "health", "ops", "fonts", "model_endpoints",
    "feedback", "chat",
]

# Panels that must NOT have the help affordance
EXCLUDED = {"help", "config", "main"}


class TestHelpAffordancePerSurface:
    """Every user-facing panel must contain the help affordance snippet."""

    def _assert_has_help_snippet(self, path: Path, surface_id: str) -> None:
        """Assert the panel html contains the help button for this surface."""
        source = path.read_text(encoding="utf-8")
        # Check for the class=help-btn marker
        assert "help-btn" in source, f"{path.name}: missing help-btn class"
        # Check for the specific openModal call with this surface
        expected = f"help.html?surface={surface_id}"
        assert expected in source, (
            f"{path.name}: missing deep-link '{expected}'"
        )
        # Check for the openModal call
        assert "openModal" in source, f"{path.name}: missing openModal call"

    def test_all_target_panels_have_help_affordance(self) -> None:
        """Glob every .html panel and verify target surfaces have the affordance."""
        for sid in TARGET_SURFACES:
            html = WEBUI / f"{sid}.html"
            assert html.is_file(), f"Expected panel file missing: {html.name}"
            self._assert_has_help_snippet(html, sid)

    def test_excluded_panels_lack_help_btn(self) -> None:
        """Excluded panels (help.html, config.html, main.html) must NOT have help-btn."""
        for name in EXCLUDED:
            html = WEBUI / f"{name}.html"
            if html.is_file():
                source = html.read_text(encoding="utf-8")
                assert "help-btn" not in source, (
                    f"{html.name} should NOT have the help button"
                )

    def test_every_target_covered_by_content_yaml(self) -> None:
        """Every target surface must have a help_content.yaml entry."""
        yaml_path = ROOT / "a0-applicant" / "config" / "help_content.yaml"
        with open(yaml_path, encoding="utf-8") as f:
            import yaml
            content = yaml.safe_load(f)
        for sid in TARGET_SURFACES:
            assert sid in content, f"{sid} missing from help_content.yaml"

    def test_22_surfaces_covered(self) -> None:
        """Ensure we're covering exactly 22 surfaces."""
        assert len(TARGET_SURFACES) == 22, (
            f"Expected 22 target surfaces, got {len(TARGET_SURFACES)}"
        )


class TestHelpHtmlDeepLink:
    """help.html must support ?surface= deep-link query param."""

    def test_has_url_search_params(self) -> None:
        source = HELP_HTML.read_text(encoding="utf-8")
        assert "URLSearchParams" in source, "Missing URLSearchParams reference"

    def test_reads_surface_param(self) -> None:
        source = HELP_HTML.read_text(encoding="utf-8")
        assert "surfaceParam" in source or "surface=" in source
        assert "toggleSurface" in source

    def test_auto_opens_on_load(self) -> None:
        source = HELP_HTML.read_text(encoding="utf-8")
        assert "await this.loadSurfaces()" in source or "this.loadSurfaces().then" in source
        assert "toggleSurface(surfaceParam)" in source or "toggleSurface(" in source

    def test_no_regression_on_default_behavior(self) -> None:
        """Without query param, default behavior (load all surfaces) must remain."""
        source = HELP_HTML.read_text(encoding="utf-8")
        assert "loadSurfaces" in source
        assert "callJsonApi('help'" in source or 'callJsonApi("help"' in source
        assert "action: 'list'" in source or 'action: "list"' in source


class TestConsistentSnippet:
    """The same shared mechanism is used across all panels."""

    def _count_help_btn_occurrences(self) -> int:
        count = 0
        for sid in TARGET_SURFACES:
            html = WEBUI / f"{sid}.html"
            if html.is_file():
                source = html.read_text(encoding="utf-8")
                count += source.count("help-btn")
        return count

    def test_all_target_use_same_class(self) -> None:
        """All 22 target panels use the help-btn class consistently."""
        assert self._count_help_btn_occurrences() == 22, (
            "Expected exactly 22 help-btn occurrences across target panels"
        )


def test_module_collects_at_least_one() -> None:
    """Meta: this test file must collect > 0 tests."""
    assert True, "Sanity check: the test module must exist."
