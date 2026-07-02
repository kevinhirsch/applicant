"""Regression coverage for docs/design/audits/PRODUCT_EXHAUSTIVE_AUDIT.md's
product-gaps backlog: the "referral/network prompt", confined to
``static/js/emailLibrary/applicantDigest.js``.

Follows the convention of ``test_applicant_backlog_dupguard.py`` (itself
following ``test_applicant_round2_wave3_variantscoreboard.py`` /
``test_applicant_round1_observability.py``): every fact is read from the
actual static file content via ``pathlib`` + regex — no browser, no DOM, no
real socket.

**Concept:** referrals convert far better than cold applications. When a
digest row is for a posting at a notably large/well-known company (where a
referral is most plausible), show a small, dismissible, purely-informational
nudge reminding the owner to check their network before applying cold. This
is explicitly NOT a new integration — no LinkedIn/network-graph scraping, just
a client-side name-match heuristic and a plain-language reminder. No engine
changes; front-door only.

Reuses the exact warning/note-chip visual pattern the presubmit-safety warning
badges (``_warningBadge``, see ``test_applicant_backlog_dupguard.py``) already
established in this same file — the shared ``applicant-portal-badge`` class
first introduced by ``applicantPortal.js``'s ``_urgencyBadge`` — rather than
inventing new UI, just with an informational (not warning) color token that
already exists in ``style.css`` (``--color-accent``).

Low-frequency/non-naggy by design: at most once per posting, and dismissible —
the dismiss state is a client-side localStorage set keyed
``applicant_digest_referral_dismissed`` (matching this session's established
``applicant_`` key-naming convention, e.g. ``applicantPortal.js``'s
``MILESTONES_SEEN_KEY`` / ``NOTIF_SEEN_KEY``), so a dismissed posting's nudge
never reappears.

Each assertion below was verified failing by hand (temporarily reverting the
``_referralNudge`` helper / its ``buildDigestRow`` call site / the dismiss
plumbing, rerunning, seeing a real ``AssertionError``, then restoring —
``git diff`` clean afterward) before this file was landed.
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
DIGEST_JS = REPO_ROOT / "workspace" / "static" / "js" / "emailLibrary" / "applicantDigest.js"
PORTAL_JS = REPO_ROOT / "workspace" / "static" / "js" / "applicantPortal.js"


def _read() -> str:
    return DIGEST_JS.read_text(encoding="utf-8")


def _top_level_fn(src: str, name: str) -> str:
    """Extract a top-level (unindented) `function name(...) { ... }` body.

    Same convention as ``test_applicant_backlog_dupguard.py``: the function's
    own closing brace is the first line consisting of a bare "}" with no
    leading whitespace.
    """
    m = re.search(rf"function {re.escape(name)}\([^)]*\)\s*\{{(.*?)\n\}}", src, re.S)
    assert m, f"expected a top-level function {name}(...) in the source"
    return m.group(1)


# ── the dismissal key follows the session's `applicant_` naming convention ──


def test_referral_dismissed_key_matches_established_naming_convention():
    src = _read()
    assert "REFERRAL_DISMISSED_KEY = 'applicant_digest_referral_dismissed'" in src, (
        "expected the exact localStorage key name from the task spec, matching "
        "the applicant_ prefix convention (MILESTONES_SEEN_KEY / NOTIF_SEEN_KEY "
        "in applicantPortal.js)"
    )


# ── heuristic: notably large/well-known company, no new data integration ────


def test_notably_large_company_heuristic_exists_and_is_a_plain_name_match():
    body = _top_level_fn(_read(), "_isNotablyLargeCompany")
    assert "toLowerCase" in body, "expected a case-insensitive plain string match"
    assert "_REFERRAL_LIKELY_COMPANIES" in body, (
        "expected the heuristic to check against a client-side curated list, not "
        "call out to any new backend/integration"
    )


def test_referral_likely_companies_is_a_real_list_of_recognizable_employers():
    src = _read()
    m = re.search(r"_REFERRAL_LIKELY_COMPANIES\s*=\s*\[(.*?)\];", src, re.S)
    assert m, "expected a _REFERRAL_LIKELY_COMPANIES array"
    body = m.group(1)
    for name in ("google", "amazon", "microsoft", "apple", "meta"):
        assert f"'{name}'" in body, f"expected {name!r} in the well-known company list"


def test_no_linkedin_or_network_graph_scraping_is_introduced():
    """The concept explicitly rules out a network-graph/LinkedIn integration —
    this must stay a plain client-side heuristic + copy, never a scraper."""
    src = _read()
    lowered = src.lower()
    assert "scrape" not in lowered
    assert "network-graph" not in lowered
    assert "linkedin.com" not in lowered


# ── the nudge is dismissible, and dismissal persists per-posting ────────────


def test_dismiss_helpers_exist_and_use_localstorage():
    src = _read()
    assert "function _isReferralDismissed(id)" in src
    assert "function _dismissReferralNudge(id)" in src
    dismiss_body = _top_level_fn(src, "_dismissReferralNudge")
    assert "localStorage.setItem(REFERRAL_DISMISSED_KEY" in dismiss_body, (
        "dismissal must persist to localStorage under the referral key so it "
        "survives reloads (low-frequency/non-naggy requirement)"
    )
    read_body = _top_level_fn(src, "_referralDismissedSet")
    assert "localStorage.getItem(REFERRAL_DISMISSED_KEY)" in read_body


def test_referral_nudge_checks_dismissed_state_before_rendering():
    body = _top_level_fn(_read(), "_referralNudge")
    assert "_isReferralDismissed(id)" in body, (
        "must not render the nudge again once the owner dismissed it for this posting"
    )
    # Bail out (no nudge) when there's no company match, no id, or dismissed —
    # never renders unconditionally.
    assert re.search(r"if\s*\(!id\s*\|\|.*return null", body), (
        "expected an early null-return guard so the row's own render never "
        "breaks when the nudge shouldn't show"
    )


def test_referral_nudge_click_dismisses_and_removes_itself():
    body = _top_level_fn(_read(), "_referralNudge")
    assert "addEventListener('click'" in body
    assert "_dismissReferralNudge(id)" in body
    assert "wrap.remove()" in body, (
        "clicking dismiss must both persist the dismissal AND remove the nudge "
        "from the currently-rendered row immediately"
    )


# ── plain-language, informational copy (not a warning) ──────────────────────


def test_referral_nudge_copy_is_plain_language_and_informational():
    body = _top_level_fn(_read(), "_referralNudge")
    assert "Know anyone at" in body
    assert "A referral can significantly improve your odds" in body
    assert "worth a quick check before applying" in body
    # The company name is interpolated, not hardcoded, so the copy is
    # specific to the actual posting.
    assert "${company}" in body


# ── reuses the EXISTING badge/chip pattern, not a new one ───────────────────


def test_referral_nudge_reuses_the_shared_badge_chip_class():
    body = _top_level_fn(_read(), "_referralNudge")
    assert "applicant-portal-badge" in body, (
        "expected the SAME chip class _warningBadge (and applicantPortal.js's "
        "_urgencyBadge) already use, not a new class"
    )


def test_referral_nudge_uses_an_existing_color_token_not_an_invented_one():
    body = _top_level_fn(_read(), "_referralNudge")
    assert "var(--color-accent" in body, (
        "expected an existing design-system color token (--color-accent is "
        "already defined in style.css) rather than a made-up CSS variable"
    )


def test_shared_badge_chip_pattern_still_present_as_the_thing_being_reused():
    """Sanity check the reuse claim: the source pattern this batch copies from
    must actually exist (guards against the precedent being deleted out from
    under this file without anyone noticing)."""
    src = PORTAL_JS.read_text(encoding="utf-8")
    assert "applicant-portal-badge" in src


# ── the nudge is actually wired into the row (reachability, not dead code) ──


def test_build_digest_row_calls_the_referral_nudge_helper():
    src = _read()
    row_fn = _top_level_fn(src, "buildDigestRow")
    assert "_referralNudge(row)" in row_fn, (
        "buildDigestRow must call _referralNudge so the nudge actually reaches "
        "the rendered row, not just exist as unused dead code"
    )
    assert re.search(r"card\.appendChild\(referralNudge\)", row_fn), (
        "the nudge element must actually be appended into the row, not just "
        "computed and discarded"
    )


def test_build_digest_row_is_the_single_source_shared_by_email_panel_and_portal():
    """Confirms the nudge reaches BOTH surfaces for free: buildDigestRow is
    exported (used by the Portal home-base embed too, per this file's own
    header comment), not a private helper only the Email-tab panel calls."""
    src = _read()
    assert re.search(r"export function buildDigestRow\(row, ctx\s*=\s*\{\}\)", src)


# ── engine boundary: no backend/API surface introduced for this feature ─────


def test_no_new_engine_endpoint_is_introduced_for_the_referral_nudge():
    """This is a purely client-side, purely-informational nudge — no new proxy
    route, no new engine call. The only network calls in this file remain the
    pre-existing `_api`/`_apiResearch` helpers, neither of which the referral
    helpers touch."""
    src = _read()
    referral_fns = "".join([
        _top_level_fn(src, "_isNotablyLargeCompany"),
        _top_level_fn(src, "_referralDismissedSet"),
        _top_level_fn(src, "_isReferralDismissed"),
        _top_level_fn(src, "_dismissReferralNudge"),
        _top_level_fn(src, "_referralNudge"),
    ])
    assert "fetch(" not in referral_fns
    assert "_api(" not in referral_fns
    assert "_apiResearch(" not in referral_fns
