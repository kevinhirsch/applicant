# Copyright 2025 Kevin Hirsch — MIT License
"""Release-readiness gate: proxy-panel coherence, sidebar wiring, theme CSS, plugin.yaml.

Issue: #859
"""

import re
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _no_cache():
    """Xdist parallel-safety sentinel."""
    pass


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
API_DIR = PROJECT_ROOT / "a0-applicant" / "api"
WEBUI_DIR = PROJECT_ROOT / "a0-applicant" / "webui"
SIDEBAR_FILE = (
    PROJECT_ROOT
    / "a0-applicant"
    / "extensions"
    / "webui"
    / "sidebar-quick-actions-main-start"
    / "hello-world.html"
)
THEME_CSS = WEBUI_DIR / "applicant-theme.css"
THEME_LINK_HREF = "/plugins/applicant/webui/applicant-theme.css"

# Backend-only API proxies (no corresponding WebUI panel)
BACKEND_ONLY = {
    "agent_runs", "base_resume", "features", "hello",
    "onboarding", "pending", "update_panel",
}

# Frontend-only panels (no corresponding API proxy)
FRONTEND_ONLY = {
    "activity", "config", "main", "shortcuts", "today", "update",
}

# Panels intentionally excluded from the main sidebar
EXCLUDED_FROM_SIDEBAR = set()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_api_basenames() -> set[str]:
    """Return set of API proxy basenames (excluding __init__.py)."""
    if not API_DIR.is_dir():
        return set()
    return {
        p.stem for p in API_DIR.iterdir()
        if p.suffix == ".py" and p.stem != "__init__"
    }


def _get_webui_basenames() -> set[str]:
    """Return set of WebUI panel basenames (excluding the css file)."""
    if not WEBUI_DIR.is_dir():
        return set()
    return {
        p.stem for p in WEBUI_DIR.iterdir()
        if p.suffix == ".html"
    }


def _get_sidebar_panels() -> set[str]:
    """Return set of panel basenames referenced in the sidebar via openModal."""
    if not SIDEBAR_FILE.is_file():
        return set()
    content = SIDEBAR_FILE.read_text(encoding="utf-8")
    pattern = r"window\.openModal\(\s*['\"](/plugins/applicant/webui/([^'\"]+)\.html)\s*['\"]\s*\)"
    return {m[1] for m in re.findall(pattern, content)}


# ---------------------------------------------------------------------------
# (a) No orphans — proxy-panel coherence
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestProxyPanelCoherence:
    """Verify every API proxy has a matching panel (or is a known exception)."""

    def test_all_api_proxies_have_panel_or_are_known_backend_only(self):
        """Every API proxy must have a matching WebUI panel or be a known backend-only proxy."""
        api = _get_api_basenames()
        panels = _get_webui_basenames()
        missing = api - panels
        unexpected = missing - BACKEND_ONLY
        assert not unexpected, (
            f"API proxies without a webui panel (and not in BACKEND_ONLY): "
            f"{sorted(unexpected)}"
        )

    def test_all_webui_panels_have_api_or_are_known_frontend_only(self):
        """Every WebUI panel must have a matching API proxy or be a known frontend-only panel."""
        api = _get_api_basenames()
        panels = _get_webui_basenames()
        missing = panels - api
        unexpected = missing - FRONTEND_ONLY
        assert not unexpected, (
            f"WebUI panels without an API proxy (and not in FRONTEND_ONLY): "
            f"{sorted(unexpected)}"
        )

    def test_known_backend_only_proxies_are_exactly_correct(self):
        """The BACKEND_ONLY set should match the actual unmatched API proxies."""
        api = _get_api_basenames()
        panels = _get_webui_basenames()
        actual_unmatched = api - panels
        assert actual_unmatched == BACKEND_ONLY, (
            f"BACKEND_ONLY mismatch. Actual unmatched: {sorted(actual_unmatched)}. "
            f"Expected (BACKEND_ONLY): {sorted(BACKEND_ONLY)}"
        )

    def test_known_frontend_only_panels_are_exactly_correct(self):
        """The FRONTEND_ONLY set should match the actual unmatched WebUI panels."""
        api = _get_api_basenames()
        panels = _get_webui_basenames()
        actual_unmatched = panels - api
        assert actual_unmatched == FRONTEND_ONLY, (
            f"FRONTEND_ONLY mismatch. Actual unmatched: {sorted(actual_unmatched)}. "
            f"Expected (FRONTEND_ONLY): {sorted(FRONTEND_ONLY)}"
        )


# ---------------------------------------------------------------------------
# (b) Sidebar wiring
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestSidebarWiring:
    """Verify every panel (except config.html) is wired in the sidebar."""

    def test_sidebar_file_exists(self):
        """The hello-world.html sidebar file must exist."""
        assert SIDEBAR_FILE.is_file(), f"Sidebar file not found: {SIDEBAR_FILE}"

    def test_all_panels_except_config_in_sidebar(self):
        """Every WebUI panel except config.html must be referenced in the sidebar."""
        panels = _get_webui_basenames()
        sidebar = _get_sidebar_panels()
        expected = panels - EXCLUDED_FROM_SIDEBAR
        missing = expected - sidebar
        assert not missing, (
            f"Panels missing from sidebar: {sorted(missing)}"
        )


    def test_no_duplicate_sidebar_entries(self):
        """No panel should appear more than once in the sidebar."""
        content = SIDEBAR_FILE.read_text(encoding="utf-8")
        pattern = r"window\.openModal\(\s*['\"](/plugins/applicant/webui/([^'\"]+)\.html)\s*['\"]\s*\)"
        paths = [m[1] for m in re.findall(pattern, content)]
        seen = set()
        dups = []
        for p in paths:
            if p in seen:
                dups.append(p)
            seen.add(p)
        assert not dups, f"Duplicate sidebar entries: {dups}"


# ---------------------------------------------------------------------------
# (c) Theme CSS
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestThemeCss:
    """Verify applicant-theme.css exists and is loaded by panels."""

    def test_theme_css_exists(self):
        """applicant-theme.css must exist."""
        assert THEME_CSS.is_file(), f"Theme CSS not found: {THEME_CSS}"

    def test_theme_css_nonempty(self):
        """Theme CSS must be non-empty."""
        assert THEME_CSS.stat().st_size > 0, "Theme CSS is empty"

    def test_health_panel_loads_theme(self):
        """Spot-check: health.html must load the theme CSS via a <link> tag."""
        health = WEBUI_DIR / "health.html"
        assert health.is_file()
        content = health.read_text(encoding="utf-8")
        assert THEME_LINK_HREF in content, (
            f"health.html missing theme <link> "
            f"(expected href containing '{THEME_LINK_HREF}')"
        )

    def test_config_panel_loads_theme(self):
        """Spot-check: config.html must load the theme CSS via a <link> tag."""
        config = WEBUI_DIR / "config.html"
        assert config.is_file()
        content = config.read_text(encoding="utf-8")
        assert THEME_LINK_HREF in content, (
            f"config.html missing theme <link> "
            f"(expected href containing '{THEME_LINK_HREF}')"
        )


# ---------------------------------------------------------------------------
# (d) plugin.yaml
# ---------------------------------------------------------------------------

PLUGIN_ROOT = PROJECT_ROOT / "a0-applicant"


@pytest.mark.unit
class TestPluginYaml:
    """Verify plugin.yaml presence and schema."""

    def test_plugin_yaml_exists(self):
        """plugin.yaml must exist at a0-applicant/ and contain valid metadata."""
        import yaml

        plugin_yaml = PLUGIN_ROOT / "plugin.yaml"
        assert plugin_yaml.is_file(), (
            f"plugin.yaml not found at {plugin_yaml}. "
            "This file is needed for plugin discovery metadata."
        )
        with open(plugin_yaml, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert isinstance(data, dict), "plugin.yaml must be a YAML dict"
        for key in ("name", "title", "description", "version"):
            val = data.get(key)
            assert isinstance(val, str) and val.strip(), (
                f"plugin.yaml key {key!r} must be a non-empty string, got {val!r}"
            )
        assert data["name"] == "applicant", (
            f'plugin.yaml name must be "applicant", got {data["name"]!r}'
        )
