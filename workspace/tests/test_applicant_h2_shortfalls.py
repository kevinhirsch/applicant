"""H2 — no silent underdelivery: the front-door states shortfalls item-level.

Pins the workspace half of the H2 honesty invariant (road-to-market Phase 1.5):

  * ``workspace/static/js/emailLibrary/applicantDigest.js`` — renders the
    engine's per-source ``source_shortfalls`` (a source that returned nothing /
    failed / was rate-limit-skipped on the last discovery run) as a strip on
    EVERY digest render, both the rows view and the empty-day view.
  * ``workspace/static/js/applicantToday.js`` + ``applicantPortal.js`` — the
    final-approval card/row renders ``payload.shortfall.summary`` (an
    incomplete pre-fill: unfilled / failed / deferred fields), so "Materials
    approved" never reads as "everything filled".
  * ``workspace/static/js/applicantCampaignSettings.js`` — each discovery
    source's row shows its ``yield_stats.last_run`` shortfall next to its
    lifetime totals.

Engine-side coverage lives in ``tests/unit/test_h2_no_silent_underdelivery.py``
(outcome recording, persistence, digest payload/email, pending-action payload).
The proxies forward engine payloads verbatim (digest:
``applicant_email_routes.get_digest``; pending actions: the portal/today
routes), so — as with ``test_applicant_discovery_live_badge_ui.py`` — the
front-door assertions here are source-composition checks on the shipped
renderers (no DOM-independent entry point cheap enough to shim).
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
JS_DIR = REPO_ROOT / "workspace" / "static" / "js"
DIGEST_JS = JS_DIR / "emailLibrary" / "applicantDigest.js"
TODAY_JS = JS_DIR / "applicantToday.js"
PORTAL_JS = JS_DIR / "applicantPortal.js"
CAMPAIGN_SETTINGS_JS = JS_DIR / "applicantCampaignSettings.js"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# ── digest: per-source shortfall strip ───────────────────────────────────────


def test_digest_shortfall_strip_reads_engine_source_shortfalls():
    src = _read(DIGEST_JS)
    fn = re.search(r"function _shortfallStrip\(payload\) \{.*?\n\}\n", src, re.S)
    assert fn, "expected a _shortfallStrip(payload) renderer"
    body = fn.group(0)
    assert "source_shortfalls" in body, "strip must read the engine's payload key"
    assert "s.message" in body, "strip renders the engine's per-source statements"
    assert "_esc(" in body, "scraped-source messages must be escaped"
    assert "return null" in body, "no shortfalls -> no strip (honest absence)"


def test_digest_renders_the_strip_on_both_rows_and_empty_views():
    src = _read(DIGEST_JS)
    fn = re.search(r"function _renderDigest\(panel, payload\) \{.*?\n\}\n", src, re.S)
    assert fn, "expected _renderDigest"
    body = fn.group(0)
    # One call in the empty-day branch (before its early return) and one after
    # the row loop — the strip must appear even when roles WERE found, so a
    # partial sweep can never read as a full one.
    assert body.count("_shortfallStrip(payload)") >= 2, (
        "the shortfall strip must render on the empty view AND the rows view"
    )


# ── final approval: incomplete pre-fill is stated on the item ────────────────


def test_today_final_card_states_the_prefill_shortfall():
    src = _read(TODAY_JS)
    fn = re.search(r"function _finalShortfallHTML\(item\) \{.*?\n\}\n", src, re.S)
    assert fn, "expected _finalShortfallHTML(item) in applicantToday.js"
    body = fn.group(0)
    assert "payload.shortfall" in body and "s.summary" in body
    assert "esc(" in body, "the engine summary must be escaped"
    # And the final-approval renderer actually composes it into the card.
    final = re.search(r"function _renderFinal\(wrap, item\) \{.*?\n\}\n", src, re.S)
    assert final and "_finalShortfallHTML(item)" in final.group(0), (
        "the Today final-approval card must render the shortfall line"
    )


def test_portal_final_row_states_the_prefill_shortfall():
    src = _read(PORTAL_JS)
    fn = re.search(r"function _finalShortfallHTML\(item\) \{.*?\n\}\n", src, re.S)
    assert fn, "expected _finalShortfallHTML(item) in applicantPortal.js"
    final = re.search(r"function _renderFinal\(item\) \{.*?\n\}\n", src, re.S)
    assert final and "_finalShortfallHTML(item)" in final.group(0), (
        "the Portal final-approval row must render the shortfall line"
    )


# ── campaign settings: per-source last-run note ──────────────────────────────


def test_sources_list_shows_each_sources_last_run_shortfall():
    src = _read(CAMPAIGN_SETTINGS_JS)
    fn = re.search(r"function _lastRunNote\(stats\) \{.*?\n\}\n", src, re.S)
    assert fn, "expected a _lastRunNote(stats) helper"
    body = fn.group(0)
    assert "last_run" in body
    for status in ("empty", "error", "rate_limited"):
        assert f"'{status}'" in body, f"last-run note must cover the {status} status"
    assert "return ''" in body, "ok / no record -> no claim"
    # Composed into the per-source row markup.
    assert "_lastRunNote(s.yield_stats)" in src
    assert "cs-source-lastrun" in src, "the note renders in the source row"
