"""P1-13 review surfacing (H4): the flagged-facts panel in the review UI.

The engine's truth gate (BALANCED) surfaces claims it cannot trace to the
profile instead of blocking them; the review session's ``redline_state``
carries them (derived fresh on every open/turn) and résumé variants carry
their generation-time flags in ``fit_scores``. This suite pins the front-door
half of that contract in ``static/js/documentLibrary.js``: the panel renders
from both sources, and each flagged fact offers exactly the two honest
one-tap paths — confirm it into the profile (the engine then stops flagging
it) or ask for its removal through the normal redline turn loop.

Follows the repo convention (``test_applicant_documentlibrary_redline_lens04
.py``): every fact is read from the shipped static file via ``pathlib`` +
string/regex checks — no browser, no DOM.
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
DOCLIB_JS = REPO_ROOT / "workspace" / "static" / "js" / "documentLibrary.js"


def _src() -> str:
    return DOCLIB_JS.read_text(encoding="utf-8")


def _flagged_block(src: str) -> str:
    """The flagged-facts panel block, from its marker comment to the panel append."""
    start = src.index("Flagged facts (truth gate, H4)")
    end = src.index("panel.appendChild(facts);", start)
    return src[start:end]


def test_review_panel_reads_flags_from_session_and_variant_fit_scores():
    """Both flag sources render through one panel: the session's LIVE
    ``redline_state.flagged_facts`` (documents) and the variant's
    generation-time ``fit_scores.flagged_facts`` fallback."""
    src = _src()
    block = _flagged_block(src)
    assert "rl.flagged_facts" in block, "live session flags must be the primary source"
    assert "item.fit_scores" in block and "fit_scores.flagged_facts" in block, (
        "variant generation-time flags must be the fallback source"
    )
    # Live flags win: the fallback is only consulted when the session has none.
    assert "!liveFlags" in block


def test_each_flagged_fact_offers_confirm_into_profile_and_remove():
    """One-tap 'that's true' confirms the fact into the profile via the
    existing attributes proxy (with confirm: true — the human IS the
    confirmation); 'remove it' goes through the normal subtract turn."""
    src = _src()
    block = _flagged_block(src)
    assert "/api/applicant/memory/attributes/ai-add" in block, (
        "confirming must reuse the existing ai-add attributes lane"
    )
    assert re.search(r"confirm:\s*true", block), (
        "the tap is the confirmation — the engine's confirm gate must be satisfied"
    )
    assert re.search(r"kind:\s*'subtract',\s*instruction:\s*fact", block), (
        "removal must ride the normal redline turn loop, not a bespoke path"
    )


def test_confirming_reopens_the_review_so_the_engine_recomputes_flags():
    """After a confirm, the panel re-opens the review (POST /review) so the
    engine re-derives the flags — the confirmed fact stops being flagged
    server-side; the UI never fakes the clearing for live sessions."""
    src = _src()
    block = _flagged_block(src)
    reopen = re.search(r"ai-add[\s\S]*?/review", block)
    assert reopen, "the confirm path must re-open the review for a server-side recompute"
    # Variant (static) flags cannot recompute — those rows hide optimistically,
    # and only those (the row removal is gated on the live-flag source).
    assert "if (liveFlags)" in block and "row.remove()" in block


def test_flagged_copy_is_plain_language_and_bounded():
    """White-label + honesty: plain words (no jargon), an explicit bounded
    render (8 rows max) with an honest '…and N more' overflow note."""
    src = _src()
    block = _flagged_block(src)
    assert "couldn’t verify" in block, "the header states plainly what happened"
    assert "flaggedFacts.slice(0, 8)" in block, "the render is bounded"
    assert "more — ask for changes below" in block, "overflow is announced, never silent"
    lowered = block.lower()
    for banned in ("fabricat", "fr-", "nfr-", "truthfulness"):
        assert banned not in lowered, f"user-facing block must not leak jargon: {banned}"


def test_panel_renders_inside_the_review_panel_not_a_new_surface():
    """The flags live inside the existing review panel flow (between the
    redline and the decision row) — an integral part of review, not a
    separate approval ceremony."""
    src = _src()
    flagged_at = src.index("Flagged facts (truth gate, H4)")
    redline_at = src.index("doclib-applicant-redline")
    approve_at = src.index("'Approve'", flagged_at)
    assert redline_at < flagged_at < approve_at
