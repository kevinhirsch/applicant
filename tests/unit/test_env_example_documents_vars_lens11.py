"""Lens 11 findings #58/#60 — .env.example must document every real config var.

Before the fix, several env vars that `applicant.app.config.Settings` actually
reads (with real defaults) had no line in `.env.example`, so an operator copying
the template to `.env` had no way to discover them exist. This test pins that
each of the previously-missing vars now has a `NAME=` assignment line in the
template.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ENV_EXAMPLE = _REPO_ROOT / ".env.example"

# Finding #58 — real config vars absent from the template.
_FINDING_58_VARS = (
    "NTFY_URL",
    "EGRESS_RESIDENTIAL",
    "TAKEOVER_DESKTOP_BASE_URL",
    "BROWSER_CHANNEL",
    "NOTIFICATIONS_LIVE",
    "DISCOVERY_LIVE",
    "BROWSER_REAL",
    "MATERIAL_RESEARCH_ENABLED",
    "CAPTCHA_STRATEGY",
    "CAPTCHA_SERVICE",
    "CAPTCHA_API_KEY",
    "LLM_SMART_ROUTING",
    "LLM_SMART_ROUTING_PREFER_LOCAL",
    "PRESUBMIT_MAX_LISTING_AGE_DAYS",
    "PRESUBMIT_DUPLICATE_COOLDOWN_DAYS",
    "PRESUBMIT_MAX_APPS_PER_COMPANY_PER_DAY",
    "PRESUBMIT_ELIGIBILITY_ENABLED",
    "PII_RETENTION_DAYS",
    "PII_RETENTION_SCHEDULE",
)

# Finding #60 — PREFIX_CACHE (validated in config.py) was completely undocumented.
_FINDING_60_VARS = ("PREFIX_CACHE",)


def _template_text() -> str:
    assert _ENV_EXAMPLE.is_file(), ".env.example must exist at the repo root"
    return _ENV_EXAMPLE.read_text()


@pytest.mark.unit
@pytest.mark.parametrize("var_name", _FINDING_58_VARS)
def test_finding_58_var_is_documented(var_name: str) -> None:
    text = _template_text()
    assert f"\n{var_name}=" in f"\n{text}", (
        f"{var_name} must appear as a '{var_name}=' assignment in .env.example"
    )


@pytest.mark.unit
@pytest.mark.parametrize("var_name", _FINDING_60_VARS)
def test_finding_60_var_is_documented(var_name: str) -> None:
    text = _template_text()
    assert f"\n{var_name}=" in f"\n{text}", (
        f"{var_name} must appear as a '{var_name}=' assignment in .env.example"
    )


@pytest.mark.unit
def test_documented_vars_have_no_obvious_secret_values() -> None:
    """Every newly-documented value must be a safe default/placeholder, never a
    real credential (e.g. a live API key or token)."""
    text = _template_text()
    lines = {
        line.split("=", 1)[0]: line.split("=", 1)[1]
        for line in text.splitlines()
        if "=" in line and not line.strip().startswith("#")
    }
    for var_name in _FINDING_58_VARS + _FINDING_60_VARS:
        assert var_name in lines, f"{var_name} missing from .env.example"
        value = lines[var_name]
        # Safe defaults are: empty, a bool, a plain number, a known enum keyword,
        # or the documented placeholder URL -- never anything that looks like a
        # live secret/token.
        assert "sk-" not in value
        assert "Bearer " not in value
        assert len(value) < 60
