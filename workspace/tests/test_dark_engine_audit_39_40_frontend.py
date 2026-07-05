"""Front-end control assertions for dark-engine audit B5 items 39 + 40.

Mirrors the "read the JS source, assert the control exists and points at the
right proxy" style already used by
``workspace/tests/test_applicant_promote_variant.py`` — hermetic (no browser,
no Node execution beyond the ``node --check`` syntax gate run separately),
just confirms the rendering code that reads the new engine fields actually
exists in the right place, so these assertions go RED if the wiring is
reverted.

Item 40 — degraded-draft badge: ``documentLibrary.js``'s per-material card
(``_applicantCard``) and the résumé-variant library (``_loadVariantLibrary``)
must render a plain-language warning when the engine reports ``degraded``.

Item 39 — "match to your past wins": ``applicantDigest.js``'s digest row
(``buildDigestRow``) must offer a "Past-wins match" control that fetches the
new owner-scoped proxy (``/api/applicant/memory/alignment/...``).
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKSPACE_DIR = REPO_ROOT / "workspace"
DOC_LIBRARY_JS = WORKSPACE_DIR / "static" / "js" / "documentLibrary.js"
DIGEST_JS = WORKSPACE_DIR / "static" / "js" / "emailLibrary" / "applicantDigest.js"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# ── item 40: degraded-draft badge on the material review card ──────────────


def _applicant_card_body() -> str:
    src = _read(DOC_LIBRARY_JS)
    fn = re.search(
        r"function _applicantCard\(item, appId, results\) \{.*?\n    function _renderApplicantReview",
        src,
        re.S,
    )
    assert fn, "expected the _applicantCard(item, appId, results) renderer"
    return fn.group(0)


def test_material_card_renders_degraded_badge_when_flagged():
    body = _applicant_card_body()
    assert "_applicantDegradedBadge(" in body
    assert "item.degraded" in body


def test_degraded_badge_helper_exists_and_reads_the_reason():
    src = _read(DOC_LIBRARY_JS)
    assert "function _applicantDegradedBadge(reason)" in src
    fn = re.search(r"function _applicantDegradedBadge\(reason\) \{.*?\n    \}\n", src, re.S)
    assert fn, "expected the _applicantDegradedBadge(reason) helper"
    assert "if (!reason) return null;" in fn.group(0)


def test_variant_library_renders_degraded_warning_for_flagged_variants():
    src = _read(DOC_LIBRARY_JS)
    fn = re.search(
        r"async function _loadVariantLibrary\(campaignId, container\) \{.*?\n    \}\n",
        src,
        re.S,
    )
    assert fn, "expected the _loadVariantLibrary(campaignId, container) renderer"
    body = fn.group(0)
    assert "v.degraded" in body
    assert "Fallback draft" in body


# ── item 39: "match to your past wins" digest-row control ──────────────────


def _build_digest_row_body() -> str:
    src = _read(DIGEST_JS)
    fn = re.search(
        r"export function buildDigestRow\(row, ctx = \{\}\) \{.*?\n\}\n", src, re.S
    )
    assert fn, "expected the buildDigestRow(row, ctx) renderer"
    return fn.group(0)


def test_digest_row_offers_a_past_wins_match_control():
    body = _build_digest_row_body()
    assert "Past-wins match" in body
    assert "row.posting_id" in body
    assert "_onAlignment(" in body


def test_past_wins_control_hits_the_owner_scoped_memory_alignment_proxy():
    src = _read(DIGEST_JS)
    fn = re.search(r"async function _onAlignment\(campaignId, row, btn, card\) \{.*?\n\}\n", src, re.S)
    assert fn, "expected the _onAlignment(campaignId, row, btn, card) handler"
    body = fn.group(0)
    # Never a direct engine URL -- the same owner-scoped `/api/applicant/*`
    # proxy convention every other digest-row action already uses.
    assert "/api/applicant/memory/alignment/" in body
    assert "encodeURIComponent(row.posting_id)" in body


def test_past_wins_control_only_offered_when_a_posting_id_exists():
    """A digest row with no posting id (defensive/malformed data) must not
    render a control that has nothing to look up."""
    body = _build_digest_row_body()
    guarded = re.search(r"if \(row\.posting_id\) \{.*?\n  \}\n", body, re.S)
    assert guarded, "expected the past-wins control gated behind `if (row.posting_id)`"
    assert "Past-wins match" in guarded.group(0)
