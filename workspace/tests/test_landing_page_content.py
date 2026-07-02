"""landing.html now actually pitches the job-application product and offers a
working sign-in path.

Before the fix the marketing page was a generic AI-chat pitch with no mention
of jobs/applications and no clear sign-in CTA. This pins: (1) at least two
``/login`` links (nav + hero) so there is always a reachable sign-in path, (2)
job-application language actually present in the hero copy, not just buried
somewhere in the page, and (3) no leaked upstream-fork codename (the same
denylist the CI white-label check enforces repo-wide), as a lightweight
regression guard specific to this heavily-rewritten file.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LANDING = _REPO_ROOT / "workspace" / "static" / "landing.html"

_DENYLIST = re.compile(r"firehouse|orwell|odysseus|smokey", re.IGNORECASE)
_LOGIN_HREF = re.compile(r"""href=["']/login["']""")
_JOB_WORDS = re.compile(r"\bjob\b|\bapply\b|\bapplication\b|\bresume\b", re.IGNORECASE)


def _read_html() -> str:
    return _LANDING.read_text(encoding="utf-8")


def test_login_href_appears_at_least_twice():
    html = _read_html()
    matches = _LOGIN_HREF.findall(html)
    assert len(matches) >= 2, (
        f"expected >= 2 href=\"/login\" CTAs (nav + hero), found {len(matches)}"
    )


def test_login_href_present_in_nav_and_hero_sections():
    html = _read_html()

    nav_match = re.search(r"<nav\b.*?</nav>", html, re.DOTALL)
    assert nav_match, "no <nav> section found"
    assert _LOGIN_HREF.search(nav_match.group(0)), "no /login link in <nav>"

    hero_match = re.search(r'<header class="hero".*?</header>', html, re.DOTALL)
    assert hero_match, "no hero <header> section found"
    assert _LOGIN_HREF.search(hero_match.group(0)), "no /login link in the hero"


def test_hero_copy_mentions_job_application_language():
    html = _read_html()
    hero_match = re.search(r'<header class="hero".*?</header>', html, re.DOTALL)
    assert hero_match, "no hero <header> section found"
    hero_html = hero_match.group(0)

    hits = _JOB_WORDS.findall(hero_html)
    assert len(hits) >= 2, (
        f"expected job/apply/application/resume language in the hero, found {hits}"
    )


def test_meta_description_also_pitches_job_applications():
    # Belt-and-suspenders: the <meta name="description"> is what shows up in
    # search results / link unfurls, so it should carry the same pitch.
    html = _read_html()
    meta_match = re.search(r'<meta name="description" content="([^"]*)"', html)
    assert meta_match, "no <meta name=\"description\"> tag found"
    assert _JOB_WORDS.search(meta_match.group(1))


def test_no_upstream_fork_codename_leaked():
    html = _read_html()
    hits = _DENYLIST.findall(html)
    assert not hits, f"upstream-fork codename(s) leaked into landing.html: {hits}"
