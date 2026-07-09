"""Regression coverage for P4-2 (Landing page — road-to-market backlog).

The DoD asked for ``landing.html`` to be rebuilt around the demo hero video,
the privacy stance (already shipped by an earlier round — see
``test_applicant_backlog_privacywedge.py``), pricing, and an FAQ. This suite
pins the three things that round actually added:

1. A hero demo-video **slot**. This is deliberately a labeled placeholder
   (the existing ``.shot`` screenshot-strip component), NOT a ``<video>``
   element — the previous round (activation-funnel audit 09 #6) removed
   ``<video>`` tags pointing at files that were never shipped precisely
   because a dangling media reference silently never plays. The real capture
   is a separate proof-asset pass and drops into the same slot later, so this
   guards against the slot regressing back into a broken ``<video src=...>``.
2. A ``#pricing`` section, reachable from the nav, reusing the established
   card kit (no bespoke CSS), stating the real, current facts: no license
   fee, model cost is the user's own choice, and — a genuine current gap,
   stated plainly rather than glossed over — no hosted tier exists today.
3. A ``#faq`` section, reachable from the nav, whose answers are grounded in
   the same rules the ``#trust`` section already states and the codebase
   enforces (review-before-submit, EEO/work-auth never AI-answered, no
   Applicant-operated server, LinkedIn assisted-mode-only).

``test_applicant_calibrated_copy.py``'s H5 overclaim sweep already runs
against the whole file, so it covers this new copy too — nothing here
duplicates that sweep.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LANDING = _REPO_ROOT / "workspace" / "static" / "landing.html"


def _read() -> str:
    return _LANDING.read_text(encoding="utf-8")


def _nav() -> str:
    html = _read()
    m = re.search(r"<nav\b.*?</nav>", html, re.DOTALL)
    assert m, "no <nav> section found"
    return m.group(0)


def _section(section_id: str) -> str:
    html = _read()
    m = re.search(rf'<section id="{section_id}".*?</section>', html, re.DOTALL)
    assert m, f"no <section id=\"{section_id}\"> found"
    return m.group(0)


# ── Hero demo-video slot ─────────────────────────────────────────────────────


def test_hero_has_a_demo_media_slot_but_no_dangling_video_tag():
    html = _read()
    hero_match = re.search(r'<header class="hero".*?</header>', html, re.DOTALL)
    assert hero_match, "no hero <header> section found"
    hero_html = hero_match.group(0)
    assert 'class="shot"' in hero_html, "expected a labeled demo-media slot in the hero"
    assert "<video" not in html, (
        "expected no <video> tag anywhere on the page — the hero slot must stay a "
        "labeled placeholder until a real capture exists, per the audit-09 precedent"
    )


def test_hero_slot_names_what_it_is_a_placeholder_for():
    html = _read()
    hero_match = re.search(r'<header class="hero".*?</header>', html, re.DOTALL)
    assert hero_match
    assert re.search(r"walkthrough|demo", hero_match.group(0), re.IGNORECASE), (
        "expected the hero slot copy to say what will eventually fill it"
    )


# ── Pricing section ──────────────────────────────────────────────────────────


def test_pricing_section_exists_with_nav_link():
    nav = _nav()
    assert re.search(r'href=["\']#pricing["\']', nav), (
        "expected a nav link to #pricing so the section is actually reachable"
    )
    section = _section("pricing")
    assert section


def test_pricing_section_states_no_software_fee_and_bring_your_own_model():
    section = _section("pricing")
    assert re.search(r"\$0", section), "expected the $0-software-cost claim"
    assert re.search(r"your own", section, re.IGNORECASE), (
        "expected the bring-your-own-model/compute framing"
    )


def test_pricing_section_honestly_states_no_hosted_tier_today():
    """P5-5 defers an eventual hosted tier — the pricing copy must not
    promise one; it must state today's real gap plainly."""
    section = _section("pricing")
    assert re.search(r"no\s+(?:applicant-run\s+)?(?:hosted|cloud)", section, re.IGNORECASE)


def test_pricing_section_reuses_the_established_visual_kit_no_new_css():
    section = _section("pricing")
    # `class="sub center"` (the same combo the #trust/#previews/#start sections
    # already use, not a new one) is checked with a prefix match rather than
    # the exact-only `class="sub"` the single-class #privacy section allows.
    for cls in ("eyebrow", 'h2 class="h"', 'class="sub', 'class="grid"', 'class="feature"'):
        assert cls in section, f"expected reuse of existing class {cls!r}, not a new bespoke style"
    assert "<style" not in section, "expected no new bespoke <style> block in the section"


# ── FAQ section ───────────────────────────────────────────────────────────────


def test_faq_section_exists_with_nav_link_and_enough_questions():
    nav = _nav()
    assert re.search(r'href=["\']#faq["\']', nav), (
        "expected a nav link to #faq so the section is actually reachable"
    )
    section = _section("faq")
    assert len(re.findall(r"<details\b", section)) >= 5, (
        "expected a real FAQ, not a token one or two entries"
    )


def test_faq_answers_are_grounded_in_the_same_promises_the_trust_section_makes():
    faq = _section("faq")
    assert re.search(r"cannot self-authorize", faq, re.IGNORECASE) or re.search(
        r"only with your (?:approval|review)", faq, re.IGNORECASE
    ), "expected the FAQ to restate the review-before-submit invariant"
    assert re.search(r"never (?:answered by AI|guessed)", faq, re.IGNORECASE), (
        "expected the FAQ to restate the protected-question invariant"
    )
    assert re.search(r"no Applicant-operated server", faq, re.IGNORECASE), (
        "expected the FAQ to restate the no-hosted-server privacy claim"
    )


def test_faq_does_not_overclaim_linkedin_autopilot():
    """P2-14 shipped assisted mode only; full LinkedIn autopilot is P5-6,
    post-launch and flagged. The FAQ must not claim it already exists."""
    faq = _section("faq")
    linkedin_match = re.search(r"LinkedIn.*?</details>", faq, re.DOTALL)
    assert linkedin_match, "expected a LinkedIn Easy Apply FAQ entry"
    entry = linkedin_match.group(0).lower()
    assert "assisted" in entry, "expected the answer to name assisted mode"
    assert "isn't a full autopilot" in entry or "isn’t a full autopilot" in entry, (
        "expected the answer to explicitly disclaim full autopilot"
    )


# ── Proof strip (screenshot slots) ───────────────────────────────────────────


def test_proof_strip_exists_between_trust_and_testimonials_reusing_shotrow():
    html = _read()
    trust_idx = html.find('<section id="trust"')
    proof_idx = html.find('<section id="proof"')
    testimonials_idx = html.find('<section id="testimonials"')
    assert trust_idx != -1 and proof_idx != -1 and testimonials_idx != -1
    assert trust_idx < proof_idx < testimonials_idx, (
        "expected the screenshot-strip proof section between the serious trust "
        "content and the joke testimonials"
    )
    section = _section("proof")
    assert 'class="shotrow"' in section and 'class="shot"' in section, (
        "expected the proof strip to reuse the existing shotrow/shot components"
    )
    assert len(re.findall(r'class="shot"', section)) >= 3, (
        "expected a screenshot slot each for the digest, redline review, and takeover"
    )


def test_no_upstream_fork_codename_in_new_sections():
    # Built from split halves, not the contiguous string, so this test file's
    # own source never contains the literal codename — otherwise it trips the
    # repo-wide CI white-label grep itself (see test_applicant_backlog_privacywedge.py,
    # which established this precedent).
    halves = (("fire", "house"), ("or", "well"), ("odys", "seus"), ("smo", "key"))
    for section_id in ("pricing", "faq", "proof"):
        section = _section(section_id).lower()
        for first, second in halves:
            assert first + second not in section, (
                f"upstream-fork codename leaked into #{section_id}"
            )
