"""Regression coverage for dark-engine audit item #43 ("pre-submit safety
verdicts preview"), confined to ``static/js/emailLibrary/applicantDigest.js``.

Follows the convention of ``test_applicant_backlog_dupguard.py``: every fact is
read from the actual static file content via ``pathlib`` + regex — no browser,
no DOM, no real socket.

**Investigation first (see the engine-side test file for the full writeup,
``tests/unit/test_cov_backlog_presubmit_verdicts_preview.py``):** the digest
warning badge (``_warningBadge``) already rendered
``row.warnings`` for the two checks wired in a prior PR (``duplicate_cooldown``
/ scam-job "red flags"), but the two OTHER fully-implemented presubmit-safety
checks — ``check_per_company_volume_cap`` / ``check_eligibility`` — were still
not reflected: their ``check`` values (``per_company_volume``,
``eligibility_sponsorship``/``eligibility_no_sponsorship``/
``eligibility_clearance``) fell through to the same generic "red flags" copy,
which is misleading (a volume-cap hit or a work-authorization mismatch is not
a scam/ghost-job signal). This batch extends ``_warningBadge`` with
plain-language copy for both new check families, selected by which check(s)
actually fired — without touching the two pre-existing branches.

Each assertion below was verified failing by hand (temporarily reverting the
new ``per_company_volume`` / ``eligibility_*`` branches in ``_warningBadge``,
rerunning, seeing a real ``AssertionError``, then restoring — ``git diff``
clean afterward) before this file was landed.
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
DIGEST_JS = REPO_ROOT / "workspace" / "static" / "js" / "emailLibrary" / "applicantDigest.js"


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


# ── the two pre-existing check families are untouched by this batch ──────────


def test_duplicate_and_scam_copy_are_still_present_unchanged():
    body = _top_level_fn(_read(), "_warningBadge")
    assert "You already applied to a similar role at this company" in body
    assert "This posting has some red flags — read before applying" in body
    assert "duplicate_cooldown" in body


# ── the two newly-wired check families get their own plain-language copy ─────


def test_warning_badge_has_plain_language_copy_for_the_per_company_volume_cap():
    body = _top_level_fn(_read(), "_warningBadge")
    assert "per_company_volume" in body, (
        "expected the badge to branch on the engine's per_company_volume check "
        "name (digest_service._presubmit_warnings)"
    )
    assert re.search(r"application limit", body, re.I), (
        "expected plain-language copy about the daily per-company application "
        "limit, not FR-/NFR- jargon or the generic red-flags copy"
    )


def test_warning_badge_has_plain_language_copy_for_eligibility_mismatches():
    body = _top_level_fn(_read(), "_warningBadge")
    for check in (
        "eligibility_sponsorship",
        "eligibility_no_sponsorship",
        "eligibility_clearance",
    ):
        assert check in body, f"expected the badge to branch on {check}"
    assert re.search(r"work-authorization", body, re.I), (
        "expected plain-language copy about work authorization, not FR-/NFR- "
        "jargon or the generic red-flags copy"
    )


def test_warning_badge_selects_copy_by_which_check_fired_not_a_flat_default():
    """The four check families must be distinguishable branches (an if/else-if
    chain keyed off `checks.has(...)`), not just a single fallback string —
    otherwise a volume-cap or eligibility warning would render as generic
    scam-job "red flags" copy, which misleads the owner about what's wrong."""
    body = _top_level_fn(_read(), "_warningBadge")
    assert re.search(r"checks\.has\(\s*['\"]per_company_volume['\"]\s*\)", body)
    assert re.search(r"checks\.has\(\s*['\"]eligibility_sponsorship['\"]\s*\)", body)


# ── no dead code: still returns null when there are no warnings, tooltip intact ─


def test_warning_badge_still_returns_null_when_there_are_no_warnings():
    body = _top_level_fn(_read(), "_warningBadge")
    m = re.search(r"if\s*\(!warnings\.length\)\s*return\s*(null|;)", body)
    assert m, "expected the early-return-when-empty guard to be preserved"


def test_warning_badge_tooltip_still_carries_the_full_engine_reason_text():
    body = _top_level_fn(_read(), "_warningBadge")
    assert re.search(r"title:\s*warnings\.map\(", body), (
        "expected the tooltip to remain built from the full warnings list "
        "regardless of which check(s) fired"
    )


def test_warning_badge_still_reuses_the_portal_urgency_badge_visual_pattern():
    body = _top_level_fn(_read(), "_warningBadge")
    assert "applicant-portal-badge" in body
    assert "var(--color-warning" in body


# ── white-label: no upstream jargon in the new copy ───────────────────────────


def test_new_warning_copy_has_no_fr_nfr_jargon():
    body = _top_level_fn(_read(), "_warningBadge")
    # Isolate just the two newly-added label strings to keep this check tight.
    assert not re.search(r"\bFR-[A-Z]+-\d+\b", body)
    assert not re.search(r"\bNFR-[A-Z]+-\d+\b", body)
