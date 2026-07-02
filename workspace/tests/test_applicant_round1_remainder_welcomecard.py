"""Regression coverage for design-audit item #19 — the first-run (pre-setup)
home used to be a bare wallpaper + washed wordmark + a plain "Type /setup"
hint, which read as broken rather than an intentional empty state. This
batch was explicitly skipped from the round-1 audit closeout (PR #578)
because it's a net-new feature that wires across ``static/index.html`` and
``static/js/models.js`` — outside that batch's file-ownership boundary — so
it lands here as its own follow-up.

Follows the convention of ``test_applicant_round1_chatmind.py``: every fact
is read from the actual static file content via ``pathlib`` + regex — no
browser, no DOM, no real socket. ``static/js/models.js`` does top-level
``document``/``fetch`` work and is not cleanly importable under a bare
``node --input-type=module``, so text/regex assertions are used throughout.

Each assertion here was verified, by hand, to actually go red when the
underlying fix is reverted (revert source -> rerun -> see the assertion
fail -> restore) per the batch's test-coverage DoD.
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
STATIC_DIR = REPO_ROOT / "workspace" / "static"
JS_DIR = STATIC_DIR / "js"
INDEX_HTML = STATIC_DIR / "index.html"
MODELS_JS = JS_DIR / "models.js"
ONBOARDING_JS = JS_DIR / "applicantOnboarding.js"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# ── The bare "Type /setup" placeholder text is gone ─────────────────────────

def test_no_type_slash_setup_placeholder_text_remains_in_welcome_surfaces():
    """The old placeholder ("Type /setup to get started." / "Type /setup, then
    choose Local models or API.") must no longer appear in index.html or
    models.js — it read as broken, not intentional, and is replaced by a
    designed welcome card. (The unrelated model-picker dropdown empty-state
    hint in models.js, out of scope for this item, is intentionally not
    touched/asserted on here.)"""
    html = _read(INDEX_HTML)
    js = _read(MODELS_JS)
    assert "Welcome, type /setup to get started." not in html
    assert "Type /setup, then choose Local models or API." not in html
    assert "welcomeSub.innerHTML = 'Type" not in js


# ── The designed welcome card exists and is built from established tokens ──

def test_welcome_setup_card_helper_exists_and_reuses_admin_card_og_card():
    """A dedicated renderer builds the glass welcome card into the existing
    `#welcome-setup` slot, composing the same `.admin-card og-card` pairing
    Portal's designed empty-state rows already use (see applicantPortal.js
    `_renderGated`) rather than hand-rolling new visual language."""
    js = _read(MODELS_JS)
    assert "function _renderWelcomeSetupCard" in js
    m = re.search(r"function _renderWelcomeSetupCard\(\)\s*\{(.*?)\n\}", js, re.S)
    assert m, "expected a _renderWelcomeSetupCard function body"
    body = m.group(1)
    assert 'getElementById(\'welcome-setup\')' in body
    assert 'class="admin-card og-card"' in body
    # Primary CTA — the exact same wizard launcher every other empty-state
    # CTA in the app already opens (window.launchApplicantSetup).
    assert "cal-btn-primary" in body
    assert "window.launchApplicantSetup" in body


def test_welcome_setup_card_copy_matches_established_wizard_voice():
    """The card's headline/description must match the tone/voice already
    established by the OOBE wizard's own Welcome step (not invented copy)."""
    models_js = _read(MODELS_JS)
    onboarding_js = _read(ONBOARDING_JS)
    assert "Let's get you set up" in models_js
    desc = "Connect a model to get started — everything else, Applicant learns as you go."
    assert desc in models_js
    # The exact same description string the wizard's Welcome step already
    # uses (applicantOnboarding.js _renderWelcome) — proves it's reused, not
    # a new voice invented for this surface.
    assert desc in onboarding_js


# ── Gating: only the genuinely-unconfigured (no model endpoints) state ─────

def test_welcome_setup_card_only_renders_in_the_no_endpoints_branch():
    """The card must be wired into the exact branch that already detects
    "no model endpoints configured at all" (`_cachedItems.length === 0`),
    not as a new always-on card, and must be explicitly torn back down the
    moment there IS at least one configured endpoint."""
    js = _read(MODELS_JS)
    no_endpoints_branch = re.search(
        r"if \(!_cachedItems \|\| _cachedItems\.length === 0\) \{(.*?)\n    \} else \{(.*?)\n    \}",
        js,
        re.S,
    )
    assert no_endpoints_branch, "expected the existing no-endpoints/else branch in refreshModels()"
    unconfigured_body, configured_body = no_endpoints_branch.groups()
    assert "_renderWelcomeSetupCard()" in unconfigured_body
    assert "_hideWelcomeSetupCard()" in configured_body
    # And make sure the show/hide pair isn't reversed.
    assert "_hideWelcomeSetupCard()" not in unconfigured_body
    assert "_renderWelcomeSetupCard()" not in configured_body


def test_welcome_setup_slot_starts_hidden_in_markup():
    """The `#welcome-setup` slot in index.html must default to hidden so it
    never flashes on before JS has determined the real configured state."""
    html = _read(INDEX_HTML)
    assert re.search(r'<div id="welcome-setup" style="display:none">\s*</div>', html)


def test_welcome_setup_card_reclaims_pointer_events_from_inert_parent():
    """`#welcome-screen` is `pointer-events:none` (it's normally just inert
    hint text floating over the chat area) — the injected card is real
    interactive content (a clickable CTA), so the renderer must explicitly
    opt it back into pointer events or the button would be unclickable."""
    js = _read(MODELS_JS)
    m = re.search(r"function _renderWelcomeSetupCard\(\)\s*\{(.*?)\n\}", js, re.S)
    assert m
    assert "pointer-events:auto" in m.group(1)
