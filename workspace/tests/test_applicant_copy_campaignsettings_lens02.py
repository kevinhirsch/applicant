"""Regression coverage for the copy & voice audit
(``docs/design/audits/exhaustive2/02_copy_voice.md``), lens 02, confined to
the search-settings renderer: ``applicantCampaignSettings.js``.

This is a copy-only pass: the big fix here is terminology drift — "campaign"
is CRM vocabulary, so every USER-FACING string is standardized on "search"
("your search", "this search", "Start a search") while the identifier
``campaign`` stays unchanged in code (function/variable names, the
``/api/applicant/campaigns`` API path, and the ``data-campaign-id`` /
``data-cs-*`` DOM attributes) — those are asserted to remain untouched below,
scoped to code tokens rather than display copy so this test does not fight
the file's own identifiers. Also: known job-board brands get their real
capitalization (``LinkedIn``, not ``Linkedin``), the funnel term "converted"
is replaced by plain "led to applications", the archive action confirms its
consequence, error toasts are mapped through ``errText()`` instead of raw
``e.message``, and user-facing apostrophes are swept to curly (’).

Three sites keep a straight apostrophe on purpose: the ``until_n_viable``
option label, the Name-input tooltip's "doesn't affect", and the Duplicate
button's "this one's criteria" — each is asserted verbatim (straight quote
and all) by pre-existing sibling-lens tests
(``test_applicant_campaign_settings_help_lens12.py``,
``test_applicant_exhaustive2_copyvoice_today_campaignsettings_gallery.py``)
that live outside this pass's one-file ownership boundary. Rewriting those
three strings to curly here would silently break those guards, so — same
as the onboarding lens-02 pass's #36/#51 — they're left as a tracked
follow-up rather than changed in this pass.

No DOM/logic changes — see the git history for the paired source commit.
Every fact is read from the actual static file content via ``pathlib`` — no
browser, no DOM, no real socket. Each assertion here was verified, by hand,
to go red when the underlying fix is reverted (temporarily restored the
pre-fix source from a file-copy backup, reran, saw a real ``AssertionError``,
then restored from the backup — never ``git stash``) before this file was
landed.
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
JS_DIR = REPO_ROOT / "workspace" / "static" / "js"
CAMPAIGN_SETTINGS_JS = JS_DIR / "applicantCampaignSettings.js"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# ── Terminology drift: "campaign" (CRM word) -> "search" in user copy ──────


def test_create_card_says_start_a_search():
    js = _read(CAMPAIGN_SETTINGS_JS)
    assert "<h2>Start a search</h2>" in js
    assert "Each search has its own criteria, sources, and learning." in js
    assert '<button type="button" class="cal-btn" id="cs-create">Start search</button>' in js
    assert "No searches yet — start one above." in js
    assert "<h2>Create a campaign</h2>" not in js
    assert "A campaign is one job search" not in js
    assert ">Create</button>" not in js
    assert "No campaigns yet" not in js


def test_toasts_say_search_not_campaign():
    js = _read(CAMPAIGN_SETTINGS_JS)
    assert "_toast('Search created')" in js
    assert "_toast('Search updated')" in js
    assert "_toast(active ? 'Search archived' : 'Search reactivated')" in js
    assert "_toast('Search duplicated')" in js
    assert "_toast('Search deleted')" in js
    assert "Campaign created" not in js
    assert "Campaign updated" not in js
    assert "Campaign archived" not in js
    assert "Campaign reactivated" not in js


def test_loading_and_offline_copy_say_search_not_campaign():
    js = _read(CAMPAIGN_SETTINGS_JS)
    assert "Loading searches…" in js
    assert "Loading campaigns…" not in js
    assert (
        "I can't connect right now — your search settings will appear once I'm back."
        not in js
    )
    assert "I can’t connect right now — your search settings will appear once I’m back." in js
    assert "campaign settings will appear once it reconnects" not in js


def test_code_identifiers_still_say_campaign_unchanged():
    """The lift-and-shift rule: don't rename code symbols, DOM ids, or the
    API path — only the display copy changes. This guards against an
    over-eager find/replace nuking the identifiers this module (and its
    proxy route + tests) still depend on."""
    js = _read(CAMPAIGN_SETTINGS_JS)
    assert "const BASE = '/api/applicant/campaigns';" in js
    assert "export async function mountApplicantCampaignSettings(host)" in js
    assert "window.mountApplicantCampaignSettings = mountApplicantCampaignSettings;" in js
    assert 'data-campaign-id="${id}"' in js
    assert "function _campaignCard(c)" in js
    assert "async function _loadCampaigns()" in js


# ── Known-brand capitalization (#47) ────────────────────────────────────────


def test_known_source_brands_get_real_capitalization():
    js = _read(CAMPAIGN_SETTINGS_JS)
    assert "linkedin: 'LinkedIn'," in js
    assert "ziprecruiter: 'ZipRecruiter'," in js
    assert "indeed: 'Indeed'," in js


# ── Archive confirms its consequence (#48) ──────────────────────────────────


def test_archive_confirms_before_acting():
    js = _read(CAMPAIGN_SETTINGS_JS)
    assert "I’ll stop working this job search until you reactivate it." in js
    assert "confirmText: 'Archive', cancelText: 'Keep active'" in js


# ── Exploration-budget label plain language (#70) ───────────────────────────


def test_exploration_budget_label_is_plain_language():
    js = _read(CAMPAIGN_SETTINGS_JS)
    assert "Trying new sources" in js
    assert "(% of my effort spent on unproven job boards)" in js
    assert "Exploration budget" not in js
    assert "% effort on new sources" not in js


# ── Run-mode tooltip + renamed option (#72) ─────────────────────────────────


def test_run_mode_has_tooltip_and_plain_last_option():
    js = _read(CAMPAIGN_SETTINGS_JS)
    # Straight apostrophe intentionally kept here — see module docstring:
    # locked verbatim by test_applicant_exhaustive2_copyvoice_today_
    # campaignsettings_gallery.py::test_campaign_settings_run_mode_
    # until_n_viable_relabeled, outside this pass's file ownership.
    assert "until_n_viable', \"Until I've found enough good matches\"" in js
    assert "Until enough viable roles" not in js
    assert "(when I stop looking for this search)" in js
    assert "Continuous: I never stop looking." in js


# ── Funnel jargon: "converted" -> "led to applications" (#84) ──────────────


def test_yield_summary_avoids_converted_jargon():
    js = _read(CAMPAIGN_SETTINGS_JS)
    assert "led to applications" in js
    assert "} converted`" not in js
    assert "converted');" not in js


# ── Raw e.message never reaches a toast; errText() used throughout ─────────


def test_error_toasts_are_mapped_through_errtext_not_raw_message():
    js = _read(CAMPAIGN_SETTINGS_JS)
    assert "errText(e)" in js
    assert "e.message" not in js
    # Spot check the toast call sites explicitly.
    assert "I couldn’t update that source: ${errText(e)}" in js
    assert "I couldn’t save that: ${errText(e)}" in js
    assert "I couldn’t duplicate that search: ${errText(e)}" in js
    assert "I couldn’t open the activity log: ${errText(e)}" in js
    assert "I couldn’t delete that search: ${errText(e)}" in js
    assert "I couldn’t create that search: ${errText(e)}" in js


# ── Curly apostrophes throughout the user-facing copy ───────────────────────


_STRAIGHT_APOSTROPHE_IN_PROSE = re.compile(r"[A-Za-z]\\?'[A-Za-z]")

# The three sites pinned to a straight apostrophe by pre-existing sibling-lens
# tests outside this pass's file ownership (see module docstring). Everything
# else in the file's user-facing copy must be curly.
_KNOWN_STRAIGHT_APOSTROPHE_LINES = {
    "  ['until_n_viable', \"Until I've found enough good matches\"],",
    "               title=\"A label to tell this search apart from your others "
    "— doesn't affect what I search for\">",
    "                title=\"Start a new search with this one's criteria and "
    "settings\">Duplicate</button>",
}


def test_no_unexpected_straight_apostrophes_outside_comments():
    """Sweep every non-comment line for a straight apostrophe sitting between
    two letters (a contraction/possessive) — the audit's cross-cutting rule
    #3 says curly (’) everywhere in user-facing copy. Comments are excluded
    (not shown to users); the three pinned exceptions above are excluded too."""
    js = _read(CAMPAIGN_SETTINGS_JS)
    offending = []
    for lineno, line in enumerate(js.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("//"):
            continue
        if line in _KNOWN_STRAIGHT_APOSTROPHE_LINES:
            continue
        if _STRAIGHT_APOSTROPHE_IN_PROSE.search(line):
            offending.append((lineno, line))
    assert not offending, f"unexpected straight apostrophes found: {offending}"


def test_curly_apostrophes_present_at_known_sites():
    js = _read(CAMPAIGN_SETTINGS_JS)
    assert "you’ve approved enough" in js
    assert "what I’ve already learned about it" in js
    assert "I’ll stop working this job search" in js
    assert "I couldn’t save that: ${errText(e)}" in js
