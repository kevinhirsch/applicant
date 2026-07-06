"""Regression coverage for the copy & voice (exhaustive2 lens 02) pass over
``workspace/static/index.html`` — see
``docs/design/audits/exhaustive2/02_copy_voice.md`` findings #188-190,
#211-219, and #237 (the `test_applicant_exhaustive2_copyvoice_today_
campaignsettings_gallery.py`` docstring explicitly notes "index.html rail
tooltips (#211-#217) ... are out of this pass's hard file scope" — this file
is that deferred follow-up pass, confined to `index.html` only).

Findings fixed here:
  * #188 (aria-label bug, 7 sites): the "What jobs to look for" criteria
    inputs (job titles / locations / work modes / keywords / salary) and the
    "Saved details" add-attribute inputs (detail name / value) all had their
    ``aria-label`` set to the placeholder EXAMPLE text (e.g.
    ``aria-label="Software Engineer, Backend Engineer"``), so a screen reader
    announced the example as the field's name instead of what the field is
    for. Each now describes the field itself.
  * #189: the sidebar "Activity" launcher (``#tool-debug-btn``) shared its
    visible name with the rail's own live-feed "Activity" button
    (``#rail-activity``) even though they open different surfaces (one is
    the chronological feed, the other is history + run controls + updates).
    Renamed the debug-launcher's visible label to "Activity & controls" to
    match its own tooltip and disambiguate it.
  * #190: the Settings "Live session" vault-adjacent card spoke of "Applicant"
    in the third person ("so Applicant can sign in for you"; "Watch Applicant
    fill out an application ... Reopen a session you closed here") — now
    first-person ("so I can sign in for you"; "Watch me fill out an
    application ... Reopen a live view you closed here"), and "Add them
    upfront" (number mismatch: "a site sign-in" is singular) is now "Add one
    up front".
  * #211-216: the icon-rail tooltips (and their sidebar list-item title
    duplicates, where present) for Activity, Results, Job Assistant, Profile,
    Daily updates, and Application Gallery all spoke in the third person
    ("your assistant", "the assistant") or used analytics/funnel jargon
    ("funnel", "converts") — rewritten first-person, plain language.
  * #217/#218: the Profile tab's own description and the "Suggested details"
    card both spoke of "the assistant" in the third person twice each —
    rewritten first-person ("I reuse... let me suggest them"; "I noticed
    these details...").
  * #237: the Pending tooltip said "across your job search" (singular) even
    though Pending is explicitly cross-search — reworded "across all your
    job searches", fixed at both its rail and sidebar-list-item copies.

Every assertion below is a source-text regex check over the static file (this
surface's established convention — see ``test_applicant_round2_wave1_
a11y_labels.py``, ``test_applicant_round1_remainder_shell.py``). No browser,
no DOM, no real socket.

Each assertion here was verified, by hand, to go RED when the corresponding
fix is temporarily reverted (via a file-copy backup, never ``git stash``) and
GREEN again once restored — see the task report for the revert-verification
transcript.
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
INDEX_HTML = REPO_ROOT / "workspace" / "static" / "index.html"


def _read() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


def _tag_with_id(html: str, element_id: str) -> str:
    """Return the full opening tag for a given `id="..."`, tolerant of
    element type and attribute order. Fails loudly if not found."""
    m = re.search(rf'<[a-zA-Z0-9]+\b[^>]*\bid="{re.escape(element_id)}"[^>]*>', html)
    assert m, f'expected an element with id="{element_id}" in index.html'
    return m.group(0)


def _attr(tag: str, name: str) -> str | None:
    m = re.search(rf'{name}="([^"]*)"', tag)
    return m.group(1) if m else None


# ══════════════════════════════════════════════════════════════════════════
# Finding #188 — aria-label bug: 7 sites echoed the placeholder EXAMPLE text
# ══════════════════════════════════════════════════════════════════════════


def test_criteria_aria_labels_describe_the_field_not_the_placeholder_example():
    """Superseded by the lens 05 a11y-deep pass (finding #64,
    ``test_applicant_a11y_indexhtml_lens05.py``): each of these fields has a
    proper visible ``<label for>``, so rather than keep a rephrased
    ``aria-label`` that still duplicates/echoes that label (lens 02's fix),
    the ``aria-label`` was removed outright and the real label now wins the
    accessible-name computation. This test only guards that the placeholder
    example is untouched and the old rephrased aria-label strings are gone."""
    html = _read()
    cases = {
        "applicant-crit-titles": "Software Engineer, Backend Engineer",
        "applicant-crit-locations": "Remote, New York, London",
        "applicant-crit-workmodes": "remote, hybrid, on-site",
        "applicant-crit-keywords": "Python, distributed systems",
        "applicant-crit-salary": "120000",
    }
    for element_id, stale_example in cases.items():
        tag = _tag_with_id(html, element_id)
        aria = _attr(tag, "aria-label")
        assert aria is None, (
            f"{element_id}: aria-label should have been removed (lens 05 "
            f"#64) so its visible <label> wins, got {aria!r}"
        )
        # the placeholder itself is untouched — only aria-label changed
        assert _attr(tag, "placeholder") == stale_example


def test_add_detail_aria_labels_describe_the_field_not_the_placeholder_example():
    """Superseded by the lens 05 a11y-deep pass (finding #64) — see the
    docstring on ``test_criteria_aria_labels_describe_the_field_not_the_
    placeholder_example`` above; same rationale applies to these two fields,
    which also have a proper visible ``<label for>``."""
    html = _read()
    cases = {
        "applicant-attr-name": "Phone number",
        "applicant-attr-value": "+1 555 0100",
    }
    for element_id, stale_example in cases.items():
        tag = _tag_with_id(html, element_id)
        aria = _attr(tag, "aria-label")
        assert aria is None, (
            f"{element_id}: aria-label should have been removed (lens 05 "
            f"#64) so its visible <label> wins, got {aria!r}"
        )
        assert _attr(tag, "placeholder") == stale_example


def test_no_aria_label_still_duplicates_a_sibling_placeholder_example():
    """Belt-and-suspenders sweep: none of the 7 known-bad aria-label values
    from the audit should be present anywhere in the file any more."""
    html = _read()
    stale_values = [
        'aria-label="Software Engineer, Backend Engineer"',
        'aria-label="Remote, New York, London"',
        'aria-label="remote, hybrid, on-site"',
        'aria-label="Python, distributed systems"',
        'aria-label="120000"',
        'aria-label="Phone number"',
        'aria-label="+1 555 0100"',
    ]
    for stale in stale_values:
        assert stale not in html, f"stale placeholder-echo aria-label still present: {stale}"


# ══════════════════════════════════════════════════════════════════════════
# Finding #189 — duplicate "Activity" nav name
# ══════════════════════════════════════════════════════════════════════════


def test_debug_launcher_label_disambiguated_from_the_activity_feed():
    html = _read()
    # tool-debug-btn's visible <span class="grow"> label, not just its title
    m = re.search(
        r'id="tool-debug-btn"[^>]*>.*?<span class="grow">([^<]*)</span>',
        html,
        re.S,
    )
    assert m, "expected #tool-debug-btn with a visible .grow label"
    assert m.group(1) == "Activity & controls"

    # the rail's own live-feed button keeps its own distinct name
    rail_tag = _tag_with_id(html, "rail-activity")
    assert _attr(rail_tag, "title") == "Activity — a live feed of what I'm doing"


# ══════════════════════════════════════════════════════════════════════════
# Finding #190 — Settings "Live session" card third-personed the product
# ══════════════════════════════════════════════════════════════════════════


def test_settings_vault_and_livesession_cards_are_first_person():
    html = _read()
    assert "so Applicant can sign in for you" not in html
    assert "Add them upfront to avoid interruptions later" not in html
    assert "so I can sign in for you. Add one up front to avoid interruptions later." in html

    assert "Watch Applicant fill out an application" not in html
    assert "Reopen a session you closed here" not in html
    assert "Watch me fill out an application, or take over to do a step yourself. Reopen a live view you closed here." in html


# ══════════════════════════════════════════════════════════════════════════
# Findings #211-216 — rail tooltips (+ sidebar list-item duplicates)
# ══════════════════════════════════════════════════════════════════════════


def test_rail_activity_tooltip_is_first_person():
    html = _read()
    tag = _tag_with_id(html, "rail-activity")
    assert _attr(tag, "title") == "Activity — a live feed of what I'm doing"
    assert _attr(tag, "aria-label") == "Activity — a live feed of what I'm doing"
    assert "what your assistant is doing" not in html


def test_rail_results_tooltip_drops_funnel_jargon():
    html = _read()
    tag = _tag_with_id(html, "rail-results")
    assert _attr(tag, "title") == "Results — how your applications are doing and what's working"
    assert _attr(tag, "aria-label") == "Results — how your applications are doing and what's working"
    assert "your funnel and what converts for you" not in html


def test_job_assistant_tooltip_is_plain_language_in_both_copies():
    html = _read()
    rail_tag = _tag_with_id(html, "rail-assistant")
    assert _attr(rail_tag, "title") == "Job Assistant — ask about your applications and what needs your attention"
    assert _attr(rail_tag, "aria-label") == "Job Assistant — ask about your applications and what needs your attention"

    list_tag = _tag_with_id(html, "tool-assistant-btn")
    assert _attr(list_tag, "title") == "Job Assistant — ask about your applications and what needs your attention"

    assert "surfaces what needs you" not in html


def test_rail_profile_tooltip_is_first_person():
    html = _read()
    tag = _tag_with_id(html, "rail-memory")
    assert _attr(tag, "title") == "Profile — the details I use to apply for you"
    assert _attr(tag, "aria-label") == "Profile — the details I use to apply for you"
    assert "what the assistant knows about you" not in html


def test_daily_updates_tooltip_is_first_person_in_both_copies():
    html = _read()
    rail_tag = _tag_with_id(html, "rail-email")
    assert _attr(rail_tag, "title") == "Daily updates — the roles I flagged for you today"
    assert _attr(rail_tag, "aria-label") == "Daily updates — the roles I flagged for you today"

    list_tag = _tag_with_id(html, "tool-email-btn")
    assert _attr(list_tag, "title") == "Daily updates — the roles I flagged for you today"

    assert "today's roles your assistant flagged" not in html
    assert "today’s roles your assistant flagged" not in html


def test_application_gallery_tooltip_is_first_person_in_both_copies():
    html = _read()
    rail_tag = _tag_with_id(html, "rail-applicant-gallery")
    assert _attr(rail_tag, "title") == "Application Gallery — screenshots and materials from my work"
    assert _attr(rail_tag, "aria-label") == "Application Gallery — screenshots and materials from my work"

    list_tag = _tag_with_id(html, "tool-applicant-gallery-btn")
    assert _attr(list_tag, "title") == "Application Gallery — screenshots and materials from my work"

    assert "your assistant's screenshots and generated materials" not in html
    assert "your assistant’s screenshots and generated materials" not in html


# ══════════════════════════════════════════════════════════════════════════
# Findings #217/#218 — Profile tab description + Suggested-details card
# ══════════════════════════════════════════════════════════════════════════


def test_profile_tab_description_is_first_person():
    html = _read()
    assert (
        "The details I reuse to fill out job applications for you — name, contact, work eligibility, "
        "and so on. Add one below, or let me suggest them; you stay in control of every value."
    ) in html
    assert "The details the assistant reuses to fill out job applications for you" not in html
    assert "let the assistant suggest them" not in html


def test_suggested_details_card_is_first_person():
    html = _read()
    assert "I noticed these details while working. Add the ones you want; ignore the rest." in html
    assert "The assistant noticed these details while working." not in html


# ══════════════════════════════════════════════════════════════════════════
# Finding #237 — Pending tooltip: singular "job search" on a cross-search view
# ══════════════════════════════════════════════════════════════════════════


def test_pending_tooltip_reads_across_all_job_searches_in_both_copies():
    html = _read()
    rail_tag = _tag_with_id(html, "rail-portal")
    assert _attr(rail_tag, "title") == "Pending — everything that needs your attention, across all your job searches"
    assert _attr(rail_tag, "aria-label") == "Pending — everything that needs your attention, across all your job searches"

    list_tag = _tag_with_id(html, "tool-portal-btn")
    assert _attr(list_tag, "title") == "Pending — everything that needs your attention, across all your job searches"

    assert "everything across your job search that needs your attention" not in html


# ── Denylist hygiene (per the task's standing instruction) ──────────────────

#: The four upstream-fork codenames CI's repo-wide white-label denylist step
#: bans from shipped artifacts. Split into two-piece tuples so the literal,
#: contiguous codename string never appears in this file's own source text.
_DENYLIST_CODENAME_HALVES = (
    ("fire", "house"),
    ("or", "well"),
    ("odys", "seus"),
    ("smo", "key"),
)


def test_new_test_file_is_denylist_clean():
    text = pathlib.Path(__file__).read_text(encoding="utf-8").lower()
    for a, b in _DENYLIST_CODENAME_HALVES:
        assert (a + b) not in text
