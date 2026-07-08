"""Regression coverage for P2-2 (Privacy policy + rights).

The DoD asks for an honest, published privacy policy (local-first storage,
data egress only to what the user actually configured) plus working, documented
export + delete mechanics, reachable from the front-door.

Rather than booting the full ``app.py`` (its lifespan pulls in Postgres/SQLite
setup, unnecessary for a static-content check), this suite reads the real
shipped source files directly — the same pattern
``test_applicant_backlog_privacywedge.py`` uses for the landing page's
``#privacy`` pitch section. That keeps the checks honest: every claim below is
grepped out of the actual file that ships, not asserted from memory.

Covers:
  * ``/privacy`` is registered as a real, unauthenticated route in
    ``workspace/app.py`` (alongside ``/login``, the existing public-page
    precedent).
  * ``workspace/static/privacy.html`` makes the load-bearing claims: local
    SQLite/Postgres storage (no Applicant-operated server), what's encrypted,
    every real egress point (model endpoint, discovery, ATS submission,
    notification fan-out), and an honest account of today's export/delete
    mechanics — including the gap (no single "delete my whole account" button)
    rather than overclaiming completeness.
  * The export/delete instructions are grounded in the ACTUAL button text
    shipped elsewhere in the app (Settings' "Download my data" button, the
    campaign Danger Zone's "Delete this search" button) — so this page can't
    silently drift from the real UI copy.
  * The policy is reachable pre-login (login page footer), post-login
    (Settings -> Account), and from the marketing landing page.
  * No upstream-fork codename, no FR-/NFR- jargon leaked into the user-facing
    page (white-label + plain-language rules).
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WORKSPACE = _REPO_ROOT / "workspace"
_APP_PY = _WORKSPACE / "app.py"
_PRIVACY_HTML = _WORKSPACE / "static" / "privacy.html"
_LOGIN_HTML = _WORKSPACE / "static" / "login.html"
_INDEX_HTML = _WORKSPACE / "static" / "index.html"
_LANDING_HTML = _WORKSPACE / "static" / "landing.html"
_CAMPAIGN_SETTINGS_JS = _WORKSPACE / "static" / "js" / "applicantCampaignSettings.js"

# Split into non-contiguous halves so this test file's own source text never
# contains the literal, contiguous codename string — the same false-positive
# precedent the repo's CI white-label denylist special-cases for
# test_landing_page_content.py / test_applicant_backlog_privacywedge.py.
_DENYLIST_HALVES = (
    ("fire", "house"),
    ("or", "well"),
    ("odys", "seus"),
    ("smo", "key"),
)


def _read(path: Path) -> str:
    assert path.exists(), f"expected {path} to exist"
    return path.read_text(encoding="utf-8")


def _privacy_html() -> str:
    return _read(_PRIVACY_HTML)


def test_privacy_route_registered_and_auth_exempt():
    """/privacy must be a real route, and reachable without logging in first
    (a prospective user reads it before they have an account) — the same
    treatment /login already gets."""
    app_src = _read(_APP_PY)
    assert re.search(r'@app\.get\("/privacy"\)', app_src), "expected a @app.get(\"/privacy\") route"
    assert re.search(r'"static/privacy\.html"', app_src), "expected the route to serve static/privacy.html"

    exempt_match = re.search(r"AUTH_EXEMPT_EXACT\s*=\s*\{.*?\}", app_src, re.DOTALL)
    assert exempt_match, "no AUTH_EXEMPT_EXACT set found"
    assert '"/privacy"' in exempt_match.group(0), (
        "/privacy must be in AUTH_EXEMPT_EXACT or an anonymous visitor gets "
        "redirected to /login before ever reaching the policy"
    )


def test_privacy_policy_claims_local_storage_not_a_hosted_server():
    html = _privacy_html()
    assert re.search(r"\bSQLite\b", html)
    assert re.search(r"\bPostgres\b", html)
    assert re.search(r"no Applicant-operated (backend|server)", html, re.IGNORECASE)


def test_privacy_policy_claims_encryption_at_rest():
    html = _privacy_html()
    assert re.search(r"encrypted at rest", html, re.IGNORECASE)
    assert re.search(r"sealed at rest|authenticated encryption", html, re.IGNORECASE)


def test_privacy_policy_names_every_real_egress_point():
    """Every place data actually leaves the box (per docs/private-mode.md and
    the adapters that implement it) must be named — omitting one would be the
    exact silent-degradation the H-series honesty rules forbid."""
    html = _privacy_html()
    # Model-endpoint egress (opt-in cloud provider vs local-only mode).
    assert re.search(r"cloud|remote.{0,20}provider", html, re.IGNORECASE)
    assert re.search(r"local-only", html, re.IGNORECASE)
    # Discovery egress (search criteria to job boards).
    assert re.search(r"job boards|search engines", html, re.IGNORECASE)
    # Automation / ATS submission — the core function.
    assert re.search(r"\bATS\b", html)
    # Opt-in notification fan-out.
    assert re.search(r"Discord", html)
    assert re.search(r"notification", html, re.IGNORECASE)


def test_privacy_policy_export_instructions_match_the_real_button():
    """The export walkthrough must name the actual shipped button, not a
    paraphrase that could drift from the UI."""
    html = _privacy_html()
    index_html = _read(_INDEX_HTML)
    assert 'id="settings-export-btn">Download my data<' in index_html, (
        "the real export button text changed — update the policy's export "
        "instructions together with it"
    )
    assert "Download my data" in html
    assert re.search(r"Settings.{0,10}Account", html, re.DOTALL)


def test_privacy_policy_delete_instructions_match_the_real_button():
    """The delete walkthrough must name the actual shipped Danger Zone button."""
    html = _privacy_html()
    campaign_js = _read(_CAMPAIGN_SETTINGS_JS)
    assert "Delete this search</button>" in campaign_js, (
        "the real campaign-delete button text changed — update the policy's "
        "delete instructions together with it"
    )
    assert "Delete this search" in html
    assert re.search(r"Danger Zone", html)


def test_privacy_policy_is_honest_about_the_account_delete_gap():
    """No single "delete my whole account" flow exists today (confirmed against
    the actual routes) — the policy must say so rather than imply a
    one-click full erasure that isn't there."""
    html = _privacy_html()
    assert re.search(r"no single\s+.delete my entire account.\s+button", html, re.IGNORECASE)


def test_privacy_policy_scopes_out_legal_entity_as_pending():
    """Legal-entity / governing-law questions belong to the ToS posture story
    (owner decision), not this engineering-authored policy — must be flagged
    as pending, not invented."""
    html = _privacy_html()
    assert re.search(r"pending", html, re.IGNORECASE)
    assert re.search(r"legal entity", html, re.IGNORECASE)


def test_privacy_policy_reachable_before_login():
    assert 'href="/privacy"' in _read(_LOGIN_HTML)


def test_privacy_policy_reachable_from_settings_account_tab():
    index_html = _read(_INDEX_HTML)
    # Scoped to the Account panel so this doesn't just match some unrelated
    # part of the (very large) SPA shell.
    account_panel = re.search(
        r'data-settings-panel="account".*?(?=<!-- ═+ [A-Z]+ TAB)', index_html, re.DOTALL
    )
    assert account_panel, "could not find the Account settings panel"
    assert 'href="/privacy"' in account_panel.group(0)
    # PR #766 review (Greptile): don't hand-roll inline color/weight on the
    # link (CLAUDE.md principle #4) — the anchor must not carry a style
    # attribute. (style.css defines no anchor class, verified before choosing
    # the plain-link form over inventing one.)
    anchor = re.search(r'<a\b[^>]*href="/privacy"[^>]*>', account_panel.group(0))
    assert anchor, "privacy anchor not found in the Account panel"
    assert "style=" not in anchor.group(0), (
        "the Settings privacy link must not hand-roll inline styles"
    )


def test_privacy_policy_reachable_from_landing_page():
    landing = _read(_LANDING_HTML)
    section = re.search(r'<section id="privacy".*?</section>', landing, re.DOTALL)
    assert section, "no #privacy section found on the landing page"
    assert 'href="/privacy"' in section.group(0)


def test_no_upstream_fork_codename_leaked():
    html = _privacy_html().lower()
    for first, second in _DENYLIST_HALVES:
        codename = first + second
        assert codename not in html, f"forbidden codename {codename!r} leaked into privacy.html"


def test_no_fr_nfr_jargon_leaked_in_user_facing_text():
    """Plain language only — no internal requirement codes in what a user
    reads (CLAUDE.md principle #3)."""
    html = _privacy_html()
    assert not re.search(r"\bFR-[A-Z]+-\d+\b", html)
    assert not re.search(r"\bNFR-[A-Z]+-\d+\b", html)
