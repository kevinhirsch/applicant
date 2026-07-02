"""Regression coverage for the three §D design-audit items (#73, #82) that
``test_applicant_round1_onboarding.py`` explicitly deferred because they
require cross-file changes outside its ``applicantOnboarding.js`` /
``style.css`` ownership boundary — they live in the Settings desktop panel
markup (``static/index.html``), optionally touching ``static/js/settings.js``.

Follows the same convention as the rest of the round-1 batch: every fact is
read from the actual static file content via ``pathlib`` + regex — no
browser, no DOM, no real socket.

Each assertion here was verified, by hand, to actually go red when the
underlying fix is reverted (temporarily restore the old markup -> rerun ->
see the assertion fail -> re-apply the fix -> rerun green) per the batch's
test-coverage DoD.
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
STATIC_DIR = REPO_ROOT / "workspace" / "static"
INDEX_HTML = STATIC_DIR / "index.html"
SETTINGS_JS = STATIC_DIR / "js" / "settings.js"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# ── #73: generic "Toggle on/off visibility..." subtitle removed ────────────
# The Settings modal used to show one static subtitle directly under the
# modal header, above the tab-switched panel content, regardless of which
# pane was active. It only ever described the "Agent Tools" pane's toggle
# list, so opening any other pane (e.g. "Add Models") showed a mismatched
# description. Every pane already carries its own accurate `.admin-toggle-sub`
# line inside its own card (e.g. the Agent Tools pane's "Enable or disable
# tools available to the AI agent."), so the fix removes the generic,
# always-shown subtitle rather than trying to keep it in sync with whichever
# pane is open.

def test_generic_settings_modal_subtitle_is_gone():
    html = _read(INDEX_HTML)
    assert "Toggle on/off visibility of tools and modules across the interface." not in html, (
        "expected the generic, pane-agnostic Settings modal subtitle to be removed "
        "since it only ever described one pane and misled every other one"
    )


def test_settings_modal_header_no_longer_followed_by_a_generic_subtitle_div():
    """The generic subtitle used to sit between the modal-header close and the
    .settings-layout container. Assert that structural gap is gone (header
    closes, then straight into the tabbed layout) rather than merely that the
    string is absent somewhere unrelated in the file."""
    html = _read(INDEX_HTML)
    # Anchored on the settings close button's aria-label (added in a later
    # round-2 a11y pass) so this still targets the Settings modal's specific
    # close button rather than the first `.close-btn` in the file.
    m = re.search(
        r'<button type="button" class="close-btn" aria-label="Close settings modal">'
        r'✖</button>\s*\n\s*</div>\s*\n\s*(<div[^>]*>)',
        html,
    )
    assert m, "expected to find the modal-header close button followed by the next container"
    assert 'class="settings-layout"' in m.group(1), (
        "expected the settings-layout div to immediately follow the modal header "
        "with no intervening generic subtitle div"
    )


def test_agent_tools_pane_keeps_its_own_accurate_subtitle():
    """The one pane the old generic text actually described (Agent Tools /
    data-settings-tab="tools") must still carry its own correct, scoped
    description so removing the generic top-level line loses no information."""
    html = _read(INDEX_HTML)
    m = re.search(r'<div data-settings-panel="tools"[^>]*>(.*?)</div>\s*\n\s*<!--', html, re.S)
    assert m, "expected to find the tools settings panel"
    body = m.group(1)
    assert "Enable or disable tools available to the AI agent." in body, (
        "expected the Agent Tools pane to keep its own scoped subtitle"
    )


# ── #82: "(Endpoints)" engineering jargon replaced with plain language ─────
# The "Add Models" / "Added Models" pane cards actually offer two connection
# kinds: a "Local" subsection (paste a local server URL, e.g. Ollama/vLLM/
# llama.cpp) and an "API" subsection (pick or paste a cloud provider like
# Anthropic/OpenAI/OpenRouter/etc. + an API key) — see the adm-add-local /
# adm-add-api subsections in index.html. "(Endpoints)" named the underlying
# /api/model-endpoints implementation, not what a user does, so it is
# replaced with "(local & cloud)", matching the two subsections the pane
# actually contains.

def test_no_engineering_endpoints_jargon_remains_in_settings_headers():
    html = _read(INDEX_HTML)
    assert "Endpoints" not in html, (
        "expected the '(Endpoints)' engineering-jargon parenthetical to be fully removed"
    )


def test_add_models_header_uses_plain_language_not_endpoints_jargon():
    html = _read(INDEX_HTML)
    m = re.search(r"Add Models <span[^>]*>\(([^)]*)\)</span></h2>", html)
    assert m, "expected to find the 'Add Models' pane header with a parenthetical qualifier"
    qualifier = m.group(1)
    assert qualifier.strip().lower() != "endpoints", (
        "expected plain language instead of the 'Endpoints' engineering term"
    )
    assert "local" in qualifier.lower() and "cloud" in qualifier.lower(), (
        "expected the qualifier to accurately reflect that the pane covers both "
        "local and cloud model connections"
    )


def test_added_models_header_uses_plain_language_not_endpoints_jargon():
    html = _read(INDEX_HTML)
    m = re.search(r"Added Models <span[^>]*>\(([^)]*)\)</span></h2>", html)
    assert m, "expected to find the 'Added Models' pane header with a parenthetical qualifier"
    qualifier = m.group(1)
    assert qualifier.strip().lower() != "endpoints", (
        "expected plain language instead of the 'Endpoints' engineering term"
    )
    assert "local" in qualifier.lower() and "cloud" in qualifier.lower(), (
        "expected the qualifier to accurately reflect that the pane covers both "
        "local and cloud model connections"
    )


def test_add_models_pane_actually_offers_both_local_and_api_subsections():
    """Guards the accuracy of the #82 relabel: the pane must genuinely contain
    both a Local and an API (cloud) subsection, not just claim to in copy."""
    html = _read(INDEX_HTML)
    m = re.search(r'<div data-settings-panel="services">(.*?)<!-- ═══ TOOLS TAB', html, re.S)
    assert m, "expected to find the services (Add Models / Added Models) settings panel"
    body = m.group(1)
    assert 'id="adm-add-local"' in body, "expected a Local connection subsection"
    assert 'id="adm-add-api"' in body, "expected an API (cloud) connection subsection"
    assert 'id="adm-epLocalUrl"' in body, "expected the local endpoint URL field"
    assert 'id="adm-epApiKey"' in body, "expected the cloud API key field"
