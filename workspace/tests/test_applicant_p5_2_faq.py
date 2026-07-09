"""Regression coverage for P5-2 (Pre-written support surface — road-to-market backlog).

The DoD asked for a top-20 predictable-question FAQ (no jobs found, empty digest,
invalid/expired model key, a CAPTCHA hit, a weak local model, "why didn't it just
apply", EEO/work-auth never AI-answered, private mode, backup/restore, cost/pace
guardrails, notifications not arriving, …), reachable in the white-labeled
front-door — not just written and forgotten in a doc nobody opens.

This is deliberately a DIFFERENT surface from ``test_applicant_p4_2_landing.py``'s
``#faq`` section: that one is pre-signup marketing copy (what Applicant promises
before you've installed it) with 7 questions. This one is the operational,
post-install support surface — Settings → Help & FAQ — with the real top-20 the
DoD asked for. Neither duplicates the other; this suite pins content unique to
the Help tab and does not re-assert the landing page's own claims.

The Help tab reuses the app's existing native ``<details>``/``<summary>`` disclosure
component (already used by ``applicantTracker.js``'s history rows and the landing
page's own accordion, and already styled globally in ``style.css`` under "RESEARCH
DETAILS EXPANDABLE SECTION") — no new widget, no new CSS, and content is static
markup (no engine round-trip), so it renders even when the engine or a model is
down, which is exactly when a self-hoster most needs it.

``docs/faq.md`` is the docs-site mirror of the same 20 questions (P3-4's eventual
docs site sources its FAQ page from that file so the two surfaces can't drift);
this suite pins both.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_INDEX = _REPO_ROOT / "workspace" / "static" / "index.html"
_FAQ_DOC = _REPO_ROOT / "docs" / "faq.md"
_OVERVIEW_DOC = _REPO_ROOT / "docs" / "overview.md"


def _index_html() -> str:
    return _INDEX.read_text(encoding="utf-8")


def _faq_doc() -> str:
    return _FAQ_DOC.read_text(encoding="utf-8")


def _balanced_div(html: str, marker: str) -> str:
    """Extract the full ``<div ...>...</div>`` that carries ``marker``, honoring
    nested ``<div>``s (unlike a naive non-greedy regex, which would stop at the
    FIRST ``</div>`` and truncate the panel)."""
    idx = html.index(marker)
    start = html.rfind("<div", 0, idx)
    assert start != -1, f"no enclosing <div> found for marker {marker!r}"
    depth = 0
    for m in re.finditer(r"<div\b|</div\s*>", html[start:]):
        depth += 1 if m.group(0).startswith("<div") else -1
        if depth == 0:
            end = start + m.end()
            return html[start:end]
    raise AssertionError(f"unbalanced <div> for marker {marker!r}")


def _help_panel() -> str:
    return _balanced_div(_index_html(), 'data-settings-panel="help"')


# ── Reachability: nav -> tab -> panel ───────────────────────────────────────


def test_help_tab_is_reachable_from_the_settings_nav_not_admin_gated():
    html = _index_html()
    m = re.search(r'<button[^>]*data-settings-tab="help"[^>]*>.*?</button>', html, re.DOTALL)
    assert m, "expected a Settings sidebar button for the help tab"
    button_html = m.group(0)
    assert "admin-only" not in button_html, (
        "every user hits 'no jobs found' / 'invalid key' questions, not just the "
        "operator — the Help tab must not be admin-gated"
    )
    assert re.search(r"Help", button_html), "expected the button to say Help"


def test_help_panel_exists_and_is_reachable_by_tab_id():
    panel = _help_panel()
    assert panel, 'expected a data-settings-panel="help" panel'
    # Every other settings panel starts hidden and is toggled by the generic
    # tab-switching plumbing (settings.js initTabs) — the Help panel's own
    # opening tag must follow the same convention, not invent its own
    # show/hide mechanism.
    opening_tag = panel.split(">", 1)[0]
    assert 'class="hidden"' in opening_tag


# ── The top-20 content, as a real accordion ─────────────────────────────────


def test_help_panel_has_at_least_20_faq_entries_as_details_accordion():
    panel = _help_panel()
    entries = re.findall(r"<details\b", panel)
    assert len(entries) >= 20, f"expected the real top-20 FAQ, found {len(entries)} <details> entries"
    # Every entry needs a summary (the clickable question) and an answer.
    assert len(re.findall(r"<summary\b", panel)) >= 20


def test_help_panel_reuses_the_existing_details_component_no_bespoke_css():
    """<details>/<summary> is already a first-class, globally-styled component
    (style.css "RESEARCH DETAILS EXPANDABLE SECTION", already used by
    applicantTracker.js and the landing page) — this surface must reuse it
    verbatim, not hand-roll a new accordion widget or a new <style> block."""
    panel = _help_panel()
    assert "<style" not in panel, "expected no new bespoke <style> block for the Help panel"
    assert "faq-item" not in panel, (
        "faq-item is the landing page's own scoped class (its CSS lives only in "
        "landing.html) — the in-app surface should reuse the plain, already-global "
        "<details>/<summary> styling instead of a landing-page-only class"
    )


# ── Grounded in real product behavior — the DoD's named topics ─────────────


def test_faq_covers_every_dod_named_predictable_question():
    panel = _help_panel()
    checks = {
        "no jobs found (discovery sources/region/keywords)": r"[Nn]o jobs are showing up in Discovery",
        "empty digest": r"digest is empty",
        "invalid/expired model key": r"model key is invalid",
        "CAPTCHA hit": r"CAPTCHA",
        "weak local model (parse-verify)": r"weak.{0,10}will it mangle",
        "review-before-submit": r"didn.t it just submit",
        "EEO never AI-answered": r"never answered by AI or guessed|EEO / demographic",
        "work-authorization": r"work-authorization questions specifically",
        "private/local-only mode": r"LLM_LOCAL_ONLY",
        "backup/restore": r"scripts/backup\.sh",
        "cost/pace guardrails": r"30/day",
        "notifications not arriving (Discord/ntfy)": r"Discord/ntfy/email notifications",
    }
    for label, pattern in checks.items():
        assert re.search(pattern, panel), f"expected the Help FAQ to cover: {label}"


def test_faq_states_the_review_before_submit_invariant_precisely():
    panel = _help_panel()
    assert re.search(r"cannot self-authorize a final submit", panel, re.IGNORECASE)


def test_faq_states_the_eeo_never_guessed_invariant_precisely():
    panel = _help_panel()
    assert re.search(r"decline to self-identify", panel, re.IGNORECASE)


def test_faq_honestly_names_current_notification_rough_edges_not_just_the_happy_path():
    """H-series honesty: don't ship an FAQ that only describes the ideal path —
    the two known-current gaps (test-send can false-positive; ntfy carries no
    priority) must be named, not glossed over."""
    panel = _help_panel()
    assert re.search(r"report success even when the live send", panel, re.IGNORECASE)
    assert re.search(r"priority flag", panel, re.IGNORECASE)


def test_faq_does_not_overclaim_linkedin_autopilot():
    panel = _help_panel()
    linkedin_match = re.search(r"LinkedIn.*?</details>", panel, re.DOTALL)
    assert linkedin_match, "expected a LinkedIn Easy Apply FAQ entry"
    entry = linkedin_match.group(0).lower()
    assert "assisted" in entry
    assert "isn't a full autopilot" in entry or "isn’t a full autopilot" in entry


# ── No filler, no jargon, no codenames ──────────────────────────────────────


def test_no_lorem_ipsum_placeholder_copy():
    panel = _help_panel()
    assert "lorem" not in panel.lower()
    assert "ipsum" not in panel.lower()
    assert "TODO" not in panel and "TBD" not in panel


def test_no_requirement_id_jargon_in_rendered_faq_text():
    panel = _help_panel()
    assert not re.search(r"\bFR-[A-Z]", panel), "expected no FR-* requirement jargon in user-facing FAQ text"
    assert not re.search(r"\bNFR-[A-Z]", panel), "expected no NFR-* requirement jargon in user-facing FAQ text"


def test_no_upstream_fork_codename_in_help_panel():
    # Built from split halves, not the contiguous string, so this test file's own
    # source never contains the literal codename and doesn't need a CI exclusion
    # (same precedent as test_applicant_p4_2_landing.py's equivalent check).
    halves = (("fire", "house"), ("or", "well"), ("odys", "seus"), ("smo", "key"))
    panel = _help_panel().lower()
    for first, second in halves:
        assert first + second not in panel, "upstream-fork codename leaked into the Help FAQ panel"


# ── docs/faq.md mirror ──────────────────────────────────────────────────────


def test_docs_faq_md_exists_with_the_real_top_20():
    doc = _faq_doc()
    headings = re.findall(r"^### (\d+)\. ", doc, re.MULTILINE)
    assert [int(n) for n in headings] == list(range(1, 21)), (
        f"expected docs/faq.md to carry exactly questions 1-20 in order, got {headings}"
    )


def test_docs_faq_md_points_at_the_in_app_surface_and_p5_1_support_machinery():
    doc = _faq_doc()
    assert re.search(r"Settings\s*→\s*Help\s*&\s*FAQ|Settings.*Help & FAQ", doc), (
        "expected docs/faq.md to state the in-app reachability chain"
    )
    assert "docs/support.md" in doc, (
        "expected docs/faq.md to point at the P5-1 support machinery doc as the "
        "next step, complementing rather than duplicating it"
    )


def test_docs_faq_md_has_no_lorem_or_codename():
    doc = _faq_doc().lower()
    assert "lorem" not in doc and "ipsum" not in doc
    halves = (("fire", "house"), ("or", "well"), ("odys", "seus"), ("smo", "key"))
    for first, second in halves:
        assert first + second not in doc


def test_docs_overview_lists_the_faq_doc():
    overview = _OVERVIEW_DOC.read_text(encoding="utf-8")
    assert "docs/faq.md" in overview, "expected docs/overview.md's doc index to list docs/faq.md"
