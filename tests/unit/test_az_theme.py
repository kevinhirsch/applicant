"""AZ (#847) — default visual identity theme: source-level assertions.

Verifies that applicant-theme.css exists, defines the required CSS variables,
and is linked from every HTML panel in the webui directory.
"""
from __future__ import annotations
from pathlib import Path

import pytest

PANELS_DIR = Path(__file__).resolve().parents[2] / "a0-applicant/webui"
THEME_CSS = PANELS_DIR / "applicant-theme.css"
THEME_LINK = '<link rel="stylesheet" href="/plugins/applicant/webui/applicant-theme.css">'


@pytest.fixture(scope="module")
def html() -> dict[str, str]:
    """Return a dict of {filename: content} for every .html in the panels dir."""
    result: dict[str, str] = {}
    for p in PANELS_DIR.glob("*.html"):
        result[p.name] = p.read_text(encoding="utf-8")
    return result


@pytest.fixture(autouse=True)
def _no_cache():
    pass


class TestApplicantTheme:
    """Source-level assertions for the default visual identity theme."""

    def test_theme_css_exists(self):
        assert THEME_CSS.exists(), f"applicant-theme.css not found at {THEME_CSS}"

    def test_theme_css_defines_core_vars(self):
        content = THEME_CSS.read_text(encoding="utf-8")
        required_vars = [
            "--color-primary",
            "--color-text",
            "--color-background",
            "--color-border",
            "--color-panel",
            "--color-text-secondary",
            "--color-danger-text",
            "--color-danger-bg",
            "--color-success-text",
            "--font-sm",
            "--font-base",
            "--space-sm",
            "--space-md",
            "--radius-sm",
            "--radius-md",
        ]
        for var in required_vars:
            assert var in content, f"CSS variable {var!r} not found in applicant-theme.css"

    def test_all_panels_link_theme(self, html: dict[str, str]):
        missing = []
        for name, content in html.items():
            if THEME_LINK not in content:
                missing.append(name)
        assert not missing, f"Theme link missing from: {', '.join(missing)}"

    def test_help_has_theme_in_head(self, html: dict[str, str]):
        help_content = html.get("help.html", "")
        head_end = help_content.find("</head>")
        assert head_end > 0, "help.html has no </head> tag"
        head_section = help_content[:head_end]
        assert THEME_LINK in head_section, (
            "help.html should have the theme <link> inside <head>, not just at line 1"
        )
