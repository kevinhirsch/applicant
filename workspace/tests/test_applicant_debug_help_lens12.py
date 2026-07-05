"""Regression coverage for exhaustive-audit-pass-2 lens 12 (help &
self-explainability) findings #10 and #35, confined to
``static/js/applicantDebug.js``.

Follows the convention of ``test_applicant_notifications_lens10.py``: every
fact is read from the actual static file content via ``pathlib`` + regex —
no browser, no DOM, no real socket. Each assertion was hand-verified to go
red when the underlying fix is reverted (backup the file to /tmp, revert the
change, rerun, see the assertion fail, restore from the backup) per the
project's revert-verify convention.

Findings covered (see ``docs/design/audits/exhaustive2/12_help_selfexplain.md``):
  * #10 — "exploration budget" taught two different mental models: a 0-100
    percent in Campaign settings (``applicantCampaignSettings.js``) and a
    0-1 decimal in the Debug modal. Debug's exploration-budget controls (the
    read-only Insights card and the editable Sources-tab input) are now
    percent-based (0-100) like Campaign settings, converting to/from the
    engine's underlying 0.0-1.0 representation (``criteria.py``
    ``set_exploration_budget``) at the UI boundary.
  * #35 — the Logs tab hardcoded ``?limit=100`` against the engine's
    500-entry ring buffer with no level/text filter, and "Download logs"
    only ever exported the capped 100 rows. The fetch now requests the
    fuller ring and a lightweight client-side level + text filter exists
    over the fetched entries.
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
JS_DIR = REPO_ROOT / "workspace" / "static" / "js"
DEBUG_JS = JS_DIR / "applicantDebug.js"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# ── #10: exploration-budget percent/decimal mismatch ────────────────────────


def test_insights_budget_card_renders_percent_not_raw_decimal():
    """The read-only Insights budget card must render a whole percent
    (0-100) like Campaign settings, not the engine's raw 0.0-1.0 fraction."""
    js = _read(DEBUG_JS)
    idx = js.index("const budgetCard = data.exploration_budget != null")
    window = js[idx : idx + 500]
    assert "Math.round(Number(data.exploration_budget) * 100)" in window, (
        "expected the Insights budget card to convert the fraction to a "
        "whole percent before rendering"
    )
    assert "}%" in window, "expected a '%' unit next to the rendered number"
    # The old bare-decimal rendering must be gone.
    assert "${esc(Number(data.exploration_budget))} —" not in js


def test_sources_budget_input_is_percent_based_0_to_100():
    """The editable exploration-budget input on the Sources tab must accept
    0-100 (percent), matching Campaign settings' 'Trying new sources' field,
    not the old 0-1 decimal range."""
    js = _read(DEBUG_JS)
    m = re.search(r'<input type="number" id="applicant-explore-budget"[^>]*>', js)
    assert m, "expected the exploration-budget input tag"
    tag = m.group(0)
    assert 'min="0"' in tag and 'max="100"' in tag, (
        "input range must be 0-100 (percent), not 0-1"
    )
    assert 'max="1"' not in tag, "the old 0-1 decimal range must be gone"
    assert "percentage" in tag.lower(), (
        "label/help text on the control should describe a percentage, not "
        "'a number between 0 and 1'"
    )
    assert "a number between 0 and 1" not in tag.lower()


def test_sources_budget_input_prepopulated_as_rounded_percent():
    """The input's initial value must be the fraction converted to a
    rounded whole percent, not the raw engine fraction."""
    js = _read(DEBUG_JS)
    assert "const budgetPct = hasBudget ? Math.round(Number(data.exploration_budget) * 100) : 0;" in js, (
        "expected a percent conversion computed once for the input's initial value"
    )
    m = re.search(r'<input type="number" id="applicant-explore-budget"[^>]*>', js)
    assert m
    assert 'value="${esc(String(budgetPct))}"' in m.group(0), (
        "input value must come from the converted percent, not the raw fraction"
    )


def test_save_handler_validates_percent_range_and_converts_back_to_fraction():
    """Saving must validate 0-100 and convert the percent back to the
    engine's expected 0.0-1.0 fraction before PUTting it — the engine's
    `set_exploration_budget` route (src/applicant/app/routers/criteria.py)
    still stores/returns a 0.0-1.0 float, so the UI boundary must convert on
    the way out, not just the way in."""
    js = _read(DEBUG_JS)
    m = re.search(
        r"btn\.addEventListener\('click', async \(\) => \{(.*?)\n  \}\);",
        js,
        re.DOTALL,
    )
    assert m, "expected the Save button's click handler"
    body = m.group(1)
    assert "pct < 0 || pct > 100" in body, "must validate the percent range 0-100"
    assert "val < 0 || val > 1" not in body, "must no longer validate a 0-1 decimal range"
    assert "/ 100" in body, "must divide the percent back down to a 0.0-1.0 fraction"
    assert "exploration_budget: val" in body, (
        "the PUT payload key must remain exploration_budget, carrying the converted fraction"
    )


def test_exploration_budget_copy_has_no_jargon():
    """White-label: no FR-/NFR- requirement IDs leak into the user-facing
    exploration-budget copy."""
    js = _read(DEBUG_JS)
    idx = js.index('<div style="font-weight:600;">Exploration budget</div>')
    window = js[idx : idx + 600]
    assert not re.search(r"\bFR-[A-Z]", window)
    assert not re.search(r"\bNFR-[A-Z]", window)


# ── #35: Logs tab hardcoded limit=100, no filter ────────────────────────────


def test_logs_fetch_uses_a_higher_limit_than_the_old_100():
    """The Logs tab must request more than the old hardcoded 100-entry cap so
    it can show closer to the engine's full 500-entry ring."""
    js = _read(DEBUG_JS)
    assert "${ADMIN}/logs?limit=100" not in js, (
        "the old hardcoded limit=100 fetch must be gone"
    )
    m = re.search(r"_fetchJSON\(`\$\{ADMIN\}/logs\?limit=(\d+)`\)", js)
    assert m, "expected a parameterized/raised limit on the logs fetch"
    assert int(m.group(1)) >= 500, (
        "the logs fetch limit should reach at least the engine's 500-entry ring"
    )


def test_logs_view_has_a_level_filter_control():
    """A level-filter <select> must exist and be wired to re-render the log
    rows on change."""
    js = _read(DEBUG_JS)
    assert 'id="applicant-logs-level"' in js
    m = re.search(r'<select id="applicant-logs-level"[^>]*>', js)
    assert m, "expected the level-filter select tag"
    assert "levelSel.addEventListener('change'" in js, (
        "the level filter must be wired to an event listener"
    )


def test_logs_view_has_a_text_filter_control():
    """A text-filter <input> must exist and be wired to re-render the log
    rows as the user types."""
    js = _read(DEBUG_JS)
    assert 'id="applicant-logs-q"' in js
    m = re.search(r'<input type="text" id="applicant-logs-q"[^>]*>', js)
    assert m, "expected the text-filter input tag"
    assert "qInput.addEventListener('input'" in js, (
        "the text filter must be wired to an event listener"
    )


def test_logs_filter_applies_to_level_and_message_text():
    """The client-side filter predicate must check both the parsed level and
    the parsed message/time text, not just one dimension."""
    js = _read(DEBUG_JS)
    idx = js.index("const renderRows = () => {")
    window = js[idx : idx + 700]
    assert "p.level !== level" in window
    assert "p.message.toLowerCase().includes(q)" in window


def test_download_logs_button_exports_the_full_fetched_set_not_just_100():
    """The Download-logs button must still export everything actually
    fetched (now up to the raised limit), independent of the current filter
    selection, so the export isn't itself capped at the old 100."""
    js = _read(DEBUG_JS)
    idx = js.index("const downloadBtn = _body().querySelector('#applicant-logs-download');")
    window = js[idx : idx + 250]
    assert "_downloadText(raw," in window, (
        "download must use the full fetched `raw` text, not a filtered subset"
    )


def test_logs_view_still_syntax_valid_shape_has_no_codenames():
    """White-label: no vendor/persona codenames in the touched Logs code."""
    js = _read(DEBUG_JS)
    idx = js.index("async function _renderLogs()")
    window = js[idx : idx + 3000]
    assert not re.search(r"firehouse|orwell|odysseus|smokey", window, re.IGNORECASE)
