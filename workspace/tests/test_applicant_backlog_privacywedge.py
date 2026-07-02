"""Regression coverage for the "self-hosted-privacy as the marketed wedge"
backlog item in ``docs/design/audits/PRODUCT_EXHAUSTIVE_AUDIT.md``.

The audit's finding: competitors (Teal, Huntr, Simplify) are cloud SaaS that
store your job-search data, resume, and application history on THEIR
servers. Applicant is genuinely self-hosted, but the landing page (already
heavily rewritten in an earlier round to pitch the job-application product
instead of a generic AI-chat product — see ``test_landing_page_content.py``)
didn't lead with or explain that differentiator.

This suite pins the new ``#privacy`` section added to
``workspace/static/landing.html`` and, specifically, that every claim it
makes is real and verifiable against this actual codebase, not marketing
fluff:

  * SQLite (front-door) / Postgres (engine) — both self-hosted, no
    Applicant-operated server (root ``CLAUDE.md`` "Commands" section: the
    engine's default DSN is a local Postgres; ``workspace/CLAUDE.md``'s
    "Data & state" section: front-door state is ``app.db`` — SQLite).
  * Secrets are Fernet-encrypted at rest with a key that lives on the user's
    own machine (``workspace/CLAUDE.md`` "Data & state": "Secrets in the DB
    ... are Fernet-encrypted via ``EncryptedText`` with the key at
    ``data/.app_key``" — also directly grepped out of
    ``workspace/core/database.py`` below, not just asserted from memory).
  * Zero third-party analytics/tracking scripts on the landing page itself —
    verified here by grepping the real file for known
    analytics/telemetry/tracker vendor signatures (google-analytics, gtag,
    segment, mixpanel, amplitude, hotjar, posthog, sentry, fullstory,
    clarity, facebook pixel, plausible, matomo), the same check performed
    manually before writing the copy.

Nothing here re-tests the existing coverage in
``test_landing_page_content.py`` (login CTAs, hero job-language, meta
description, codename denylist) — only the new ``#privacy`` section's
content and its claims.

Every ``test_*`` below was verified failing first: the ``#privacy`` section
was temporarily deleted from ``landing.html`` (and, separately, the
``EncryptedText``/Fernet lines were temporarily commented out of
``core/database.py`` for the source-grounding test) and each corresponding
test produced a real ``AssertionError`` / ``pytest.fail`` before the file was
restored to its original content and the suite re-run to confirm green.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LANDING = _REPO_ROOT / "workspace" / "static" / "landing.html"
_DATABASE_PY = _REPO_ROOT / "workspace" / "core" / "database.py"

# Split into non-contiguous halves so this test file's own source text never
# contains the literal, contiguous codename string (the exact false-positive
# pattern the repo's CI white-label denylist step special-cases for
# test_landing_page_content.py — see that file's precedent).
_DENYLIST_HALVES = (
    ("fire", "house"),
    ("or", "well"),
    ("odys", "seus"),
    ("smo", "key"),
)

_ANALYTICS_SIGNATURES = re.compile(
    r"google-analytics|googletagmanager|gtag\(|segment\.com|mixpanel|"
    r"amplitude\.com|hotjar|posthog|sentry\.io|fullstory|clarity\.ms|"
    r"connect\.facebook\.net|fbevents|plausible\.io|matomo",
    re.IGNORECASE,
)


def _read_landing() -> str:
    return _LANDING.read_text(encoding="utf-8")


def _privacy_section() -> str:
    html = _read_landing()
    match = re.search(r'<section id="privacy".*?</section>', html, re.DOTALL)
    assert match, "no <section id=\"privacy\"> found in landing.html"
    return match.group(0)


def test_privacy_section_exists_with_nav_link():
    html = _read_landing()
    assert re.search(r'<section id="privacy"', html), "expected a #privacy section"
    nav_match = re.search(r"<nav\b.*?</nav>", html, re.DOTALL)
    assert nav_match, "no <nav> section found"
    assert re.search(r'href=["\']#privacy["\']', nav_match.group(0)), (
        "expected a nav link to #privacy so the new section is actually reachable, "
        "not an orphaned anchor"
    )


def test_privacy_section_names_the_real_competitors_and_the_wedge():
    section = _privacy_section()
    for competitor in ("Teal", "Huntr", "Simplify"):
        assert competitor in section, f"expected competitor {competitor!r} named in the #privacy section"
    assert re.search(r"cloud|servers|hosted", section, re.IGNORECASE), (
        "expected the section to explain competitors store data on their own servers"
    )


def test_privacy_section_claims_sqlite_and_postgres_not_a_hosted_server():
    section = _privacy_section()
    assert re.search(r"\bSQLite\b", section), "expected the SQLite (front-door) claim"
    assert re.search(r"\bPostgres\b", section), "expected the Postgres (engine) claim"
    assert re.search(r"no Applicant-operated server", section, re.IGNORECASE)


def test_privacy_section_claims_are_grounded_in_the_real_encryption_source():
    """The Fernet / encryption-key claim must not just be prose on the landing
    page — the underlying fact must actually be true in the source it
    describes (workspace/core/database.py), so this can never quietly drift
    into an unverified claim."""
    section = _privacy_section()
    assert re.search(r"Fernet-encrypted", section)
    assert re.search(r"encryption key", section, re.IGNORECASE)

    db_src = _DATABASE_PY.read_text(encoding="utf-8")
    assert "Fernet-encrypted" in db_src, (
        "core/database.py no longer documents Fernet encryption — "
        "the landing-page claim would no longer be grounded"
    )
    assert "data/.app_key" in db_src, (
        "core/database.py no longer documents the on-disk key path — "
        "the landing-page claim would no longer be grounded"
    )


def test_privacy_section_claims_no_tracking_scripts():
    section = _privacy_section()
    assert re.search(r"tracking scripts|no analytics|no telemetry", section, re.IGNORECASE)


def test_landing_html_actually_has_zero_analytics_signatures():
    """Ground truth check for the "zero tracking scripts on this page" claim:
    grep the real, shipped landing.html for known analytics/telemetry/
    tracker vendor signatures. If this ever fails, the landing-page claim
    would be false and must be fixed (either remove the tracker or rewrite
    the claim) rather than the test loosened."""
    html = _read_landing()
    hits = _ANALYTICS_SIGNATURES.findall(html)
    assert not hits, f"landing.html contains analytics/tracking signatures: {hits}"


def test_no_upstream_fork_codename_leaked_in_new_section():
    section = _privacy_section().lower()
    for first, second in _DENYLIST_HALVES:
        codename = first + second
        assert codename not in section, f"forbidden codename {codename!r} leaked into #privacy section"


def test_privacy_section_matches_established_visual_kit_no_new_css():
    """Reuse the page's existing .eyebrow/.h/.sub/.grid/.feature kit — this is
    copy + a section using the established pattern, not a redesign with new
    bespoke styling."""
    section = _privacy_section()
    for cls in ("eyebrow", "h2 class=\"h\"", "class=\"sub\"", "class=\"grid\"", "class=\"feature\""):
        assert cls in section, f"expected reuse of existing class {cls!r}, not a new bespoke style"
    assert "<style" not in section, "expected no new bespoke <style> block in the section"
