"""AZ1-2 (#830) — the OOBE wizard panel contract (source assertions).

The wizard is browser-rendered HTML/JS (full E2E belongs in the P0-6 Playwright harness),
so here we pin the load-bearing contract at the source level, like the repo's other JS gates.
"""
from pathlib import Path

import pytest

WIZARD = Path(__file__).resolve().parents[2] / "a0-applicant/webui/main.html"


@pytest.fixture(scope="module")
def html() -> str:
    return WIZARD.read_text(encoding="utf-8")


def test_drives_the_engine_through_the_onboarding_proxy(html):
    assert 'callJsonApi("onboarding", { action: "state" })' in html
    assert 'action: "section"' in html and 'callJsonApi("onboarding"' in html
    assert 'callJsonApi("onboarding", { action: "complete" })' in html


def test_all_twelve_intake_sections_present(html):
    for sid in ["identity", "work_authorization", "location", "target_roles", "compensation",
                "work_history", "education", "references", "certifications", "key_attributes",
                "eeo", "campaign_criteria"]:
        assert f'id:"{sid}"' in html, f"wizard is missing intake section {sid!r}"


def test_eeo_defaults_to_decline(html):
    assert 's.id === "eeo"' in html
    assert 'this.form[f.k] = "Decline to self-identify"' in html  # pre-filled decline (FR-ATTR-6)


def test_optional_sections_are_skippable(html):
    assert "optional:true" in html          # references + certifications
    assert "async skip()" in html and 'x-if="current.optional"' in html


def test_completion_renders_engine_readiness_verbatim(html):
    # finish reads the engine's complete response; ready == 200, else apply_missing from the 409
    assert 'callJsonApi("onboarding", { action: "complete" })' in html
    assert "readyState.apply_ready" in html
    assert "readyState.apply_missing" in html


def test_resumable_reopens_at_first_incomplete(html):
    assert "jumpToFirstIncomplete" in html
    assert "sections_complete" in html  # completeness is the engine's, not client-derived
