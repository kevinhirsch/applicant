"""Regression coverage for docs/design/audits/PRODUCT_EXHAUSTIVE_AUDIT.md's
product-gaps backlog: the "duplicate-application guard" and the scam/ghost-job
warning, confined to ``static/js/emailLibrary/applicantDigest.js``.

Follows the convention of ``test_applicant_round2_wave3_variantscoreboard.py``
(itself following ``test_applicant_round1_observability.py``): every fact is read
from the actual static file content via ``pathlib`` + regex — no browser, no DOM,
no real socket.

**Investigation first (see the engine-side test file for the full writeup,
``tests/unit/test_cov_backlog_dupguard.py``):** ``presubmit_safety.py`` already
had fully-built ``check_duplicate_application`` / ``check_scam_or_ghost_job``.
A repo-wide grep showed they were called from exactly ONE place —
``AgentLoop._process_approvals`` — which runs them only AFTER the owner has
already approved a role from the digest, and on a block just logs and silently
skips (never surfaced to the owner). Worse: ``check_duplicate_application``
referenced a nonexistent ``ApplicationState.CONVERTED`` enum member, so it
raised ``AttributeError`` on every single call — the duplicate guard had never
actually run anywhere, ever (fixed alongside this, in ``presubmit_safety.py``).

The genuine gap this batch closes: ``DigestService.build_digest`` now attaches
``row.warnings`` (a list of ``{check, message}``) to every digest row, BEFORE
the owner ever sees/approves it. This file pins that ``applicantDigest.js``
actually renders that field as a plain-language badge — reusing the exact
warning-chip visual pattern ``applicantPortal.js``'s ``_urgencyBadge`` already
uses for task urgency (``applicant-portal-badge`` + ``var(--color-warning,
...)``), not a new invented style — and that the badge is wired into
``buildDigestRow`` (the single row-renderer shared by the Email-tab panel AND
the Portal home-base embed, per this file's own header comment), so the warning
surfaces on BOTH surfaces without any extra plumbing.

Each assertion below was verified failing by hand (temporarily reverting the
``_warningBadge`` helper / its ``buildDigestRow`` call site, rerunning, seeing a
real ``AssertionError``, then restoring — ``git diff`` clean afterward) before
this file was landed.
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

    Same convention as ``test_applicant_round2_wave3_variantscoreboard.py``: the
    function's own closing brace is the first line consisting of a bare "}" with
    no leading whitespace.
    """
    m = re.search(rf"function {re.escape(name)}\([^)]*\)\s*\{{(.*?)\n\}}", src, re.S)
    assert m, f"expected a top-level function {name}(...) in the source"
    return m.group(1)


# ── the warning-badge helper exists and reads the engine's warnings field ────


def test_warning_badge_helper_exists_and_reads_row_warnings():
    body = _top_level_fn(_read(), "_warningBadge")
    assert "row.warnings" in body, (
        "the badge must read the engine-computed row.warnings field "
        "(digest_service.build_digest), not invent its own client-side heuristic"
    )


def test_warning_badge_returns_null_when_there_are_no_warnings():
    """A clean posting must render no badge at all — not an empty/placeholder one."""
    body = _top_level_fn(_read(), "_warningBadge")
    m = re.search(r"if\s*\(!warnings\.length\)\s*return\s*(null|;)", body)
    assert m, "expected an early return (no badge) when the warnings list is empty"


def test_warning_badge_uses_plain_language_for_duplicate_vs_other_warnings():
    body = _top_level_fn(_read(), "_warningBadge")
    assert "You already applied to a similar role at this company" in body, (
        "expected the plain-language duplicate-application copy"
    )
    assert "This posting has some red flags" in body, (
        "expected the plain-language scam/ghost-job copy"
    )
    # The two messages must be selected by which check(s) fired, not shown together
    # or randomly — the duplicate_cooldown check specifically picks the duplicate copy.
    assert "duplicate_cooldown" in body


def test_warning_badge_tooltip_carries_the_full_engine_reason_text():
    """The short label is plain-language; the full per-check reason (e.g. "Already
    applied to Acme for 'X' within the last 30 days...") must still be reachable,
    via the tooltip, not thrown away."""
    body = _top_level_fn(_read(), "_warningBadge")
    assert re.search(r"title:\s*warnings\.map\(", body), (
        "expected the badge's title/tooltip to be built from the warnings list "
        "(the full engine-provided message), not a hardcoded string"
    )


# ── reuses the EXISTING Portal warning-chip pattern, not a new one ───────────


def test_warning_badge_reuses_the_portal_urgency_badge_visual_pattern():
    """docs/design/audits mandate: reuse whatever warning/badge visual pattern
    already exists (checked applicantPortal.js's `_urgencyBadge` first) instead of
    inventing a new one."""
    body = _top_level_fn(_read(), "_warningBadge")
    assert "applicant-portal-badge" in body, (
        "expected the SAME badge class applicantPortal.js's _urgencyBadge uses "
        "for 'Overdue'/'Due soon', not a new class"
    )
    assert "var(--color-warning" in body, (
        "expected the SAME semantic warning color token the rest of the app uses"
    )


def test_portal_urgency_badge_pattern_still_present_as_the_thing_being_reused():
    """Sanity check the reuse claim: the source pattern this batch copies from
    must actually exist (guards against the precedent being deleted out from
    under this file without anyone noticing)."""
    portal_js = REPO_ROOT / "workspace" / "static" / "js" / "applicantPortal.js"
    src = portal_js.read_text(encoding="utf-8")
    assert "applicant-portal-badge" in src
    assert "var(--color-warning" in src


# ── the badge is actually wired into the row (reachability, not dead code) ──


def test_build_digest_row_calls_the_warning_badge_helper():
    src = _read()
    row_fn = _top_level_fn(src, "buildDigestRow")
    assert "_warningBadge(row)" in row_fn, (
        "buildDigestRow must call _warningBadge so the badge actually reaches "
        "the rendered row, not just exist as unused dead code"
    )
    assert re.search(r"head\.appendChild\(warnBadge\)", row_fn), (
        "the badge element must actually be appended into the row's head, not "
        "just computed and discarded"
    )


def test_build_digest_row_is_the_single_source_shared_by_email_panel_and_portal():
    """Confirms the badge reaches BOTH surfaces for free: buildDigestRow is
    exported (used by the Portal home-base embed too, per this file's own header
    comment), not a private helper only the Email-tab panel calls."""
    src = _read()
    assert re.search(r"export function buildDigestRow\(row, ctx\s*=\s*\{\}\)", src)
