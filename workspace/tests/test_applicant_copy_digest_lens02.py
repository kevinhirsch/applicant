"""Regression coverage for two threads confined to a single file,
``workspace/static/js/emailLibrary/applicantDigest.js``:

1. **Lens 02 (copy & voice) cleanup** — ``docs/design/audits/exhaustive2/
   02_copy_voice.md``. By the time this pass landed, essentially every
   digest-panel finding numbered 85-137 in that audit (third-person
   "the assistant" self-reference, "campaign" vs "search" drift, raw
   ``Request failed (…)``/``e.message`` toasts, "research run" jargon, the
   to-do-list grammar bug, etc.) had already been applied and is covered by
   ``test_applicant_copy_voice_02_documents_digest.py`` and
   ``test_applicant_help_selfexplain_12.py``. This file adds regression
   coverage for the two remaining, previously-untested strings that still
   needed the audit's cross-cutting rule #3 (curly apostrophes, "sweep the
   applicant lane once") applied: the per-company application-limit warning
   badge and the past-wins alignment line. (Every OTHER straight apostrophe
   still present in this file is intentionally left alone here — those exact
   strings are pinned verbatim, straight quote included, by the two test
   files named above, so "curly-ifying" them would be a regression against
   an existing, unrelated test lane rather than a real fix.)

2. **DISC-10** — a bug fix: ``_onBulkDecline`` asked for one shared decline
   reason to cover an entire batch, then, unlike its sibling ``_onPass``
   (fixed for the single-row case per audit 04-#53, see
   ``test_applicant_digest_resilience_lens04.py``), threw the typed reason
   away the instant the prompt resolved — regardless of whether the
   follow-up per-row POSTs actually succeeded. A flaky batch decline forced
   the user to retype the same shared reason for the whole group on retry.
   Fix: a module-level ``_lastBulkDeclineReason`` string (one shared slot,
   not keyed by row id, since one reason covers the whole batch) preserves
   the typed text across a batch with at least one failure and prefills the
   next ``styledPrompt`` call's ``defaultValue``; it is cleared only once
   every row in a given batch attempt has gone through cleanly.

Every assertion below follows this repo's established convention (see the
two files named above): read the actual static file via ``pathlib``/regex,
plus one real ``node`` execution of the extracted bulk-decline flow against
stub collaborators. Each was hand-verified to go RED against a backup of the
pre-fix source (temporarily restored via a ``cp``-made copy, never
``git stash``) and GREEN again against the fixed file.
"""

from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess
import textwrap

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
JS_DIR = REPO_ROOT / "workspace" / "static" / "js"
DIGEST_JS = JS_DIR / "emailLibrary" / "applicantDigest.js"

_HAS_NODE = shutil.which("node") is not None


def _read() -> str:
    return DIGEST_JS.read_text(encoding="utf-8")


def _find_function(src: str, name: str) -> str:
    """Extract a top-level `function name(...) { ... }` (or `async function`)
    body via brace counting, mirroring the same helper already established in
    test_applicant_copy_voice_02_documents_digest.py and
    test_applicant_help_selfexplain_12.py."""
    m = re.search(rf"function {re.escape(name)}\([^)]*\)\s*\{{", src)
    assert m, f"expected to find function {name}"
    start = m.end()
    depth = 1
    i = start
    while depth > 0:
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
        i += 1
    return src[start : i - 1]


def _extract(src: str, pattern: str, label: str) -> str:
    m = re.search(pattern, src, re.S)
    assert m, f"expected to find {label} in {DIGEST_JS}"
    return m.group(0)


@pytest.fixture(scope="module")
def node_available():
    if not _HAS_NODE:
        pytest.skip("node binary not on PATH")


def _run_node(script: str) -> dict:
    res = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=REPO_ROOT / "workspace",
        capture_output=True,
        timeout=15,
        text=True,
    )
    assert res.returncode == 0, f"node failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    out_lines = [ln for ln in res.stdout.splitlines() if ln.strip()]
    assert out_lines, "node produced no stdout"
    return json.loads(out_lines[-1])


def test_node_check_applicant_digest_js(node_available):
    """Syntax smoke: the module every assertion below reads from must parse."""
    res = subprocess.run(
        ["node", "--check", str(DIGEST_JS)],
        capture_output=True,
        timeout=15,
        text=True,
    )
    assert res.returncode == 0, f"node --check failed:\n{res.stderr}"


# ═══════════════════════════════════════════════════════════════════════
# Lens 02 — curly-apostrophe sweep (cross-cutting rule #3), the two
# strings this pass actually still needed to touch.
# ═══════════════════════════════════════════════════════════════════════


def test_warning_badge_per_company_limit_uses_curly_apostrophes():
    body = _find_function(_read(), "_warningBadge")
    assert "You’ve hit today’s application limit for this company" in body
    assert "You've hit today's application limit for this company" not in body


def test_alignment_past_wins_line_uses_curly_apostrophe():
    body = _find_function(_read(), "_onAlignment")
    assert "with roles you’ve landed before." in body
    assert "with roles you've landed before." not in body


def test_no_banned_codenames_in_digest_js():
    src = _read().lower()
    for codename in ("firehouse", "orwell", "odysseus", "smokey", "hermes-agent"):
        assert codename not in src, f"white-label denylist term {codename!r} leaked into applicantDigest.js"


# ═══════════════════════════════════════════════════════════════════════
# DISC-10 — bulk-decline shared reason survives a failed batch POST
# ═══════════════════════════════════════════════════════════════════════


def test_bulk_decline_reason_cache_exists():
    src = _read()
    assert re.search(r"let _lastBulkDeclineReason\s*=\s*'';", src), (
        "expected a module-level _lastBulkDeclineReason string to preserve "
        "the shared batch decline reason across a failed submit"
    )


def test_on_bulk_decline_prefills_from_and_writes_to_the_reason_cache():
    src = _read()
    on_bulk_decline = _find_function(src, "_onBulkDecline")
    assert re.search(r"defaultValue:\s*_lastBulkDeclineReason", on_bulk_decline), (
        "the preserved batch reason must be threaded into styledPrompt's "
        "defaultValue so a retry starts prefilled, not blank"
    )
    # The cache must be written AFTER the per-row loop finishes (so it can
    # see whether any row failed), and must only ever hold the reason when at
    # least one row failed — cleared the moment the whole batch went through.
    loop_end_idx = on_bulk_decline.index("_updateBulkBar(panel);")
    fail_branch_idx = on_bulk_decline.index("if (fail) {")
    set_idx = on_bulk_decline.index("_lastBulkDeclineReason = reason.trim();")
    clear_idx = on_bulk_decline.index("_lastBulkDeclineReason = '';", fail_branch_idx)
    assert loop_end_idx < fail_branch_idx < set_idx < clear_idx, (
        "expected: loop finishes -> check `fail` -> set the cache on failure, "
        "clear it on full success, in that order"
    )
    # Never let the previous (unrelated single-row) cache be confused with
    # this shared one, or vice versa.
    assert "_lastDeclineReasonByRow" not in on_bulk_decline


def test_bulk_decline_reason_preserved_on_partial_failure_and_cleared_once_batch_clears(
    node_available,
):
    """Real execution: a 2-row batch decline where the first row's POST fails
    and the second succeeds must preserve the typed reason for a retry. Once
    a retry of the remaining (still-selected) row succeeds, the cache must be
    empty again — mirroring the single-row #53 fix's success/failure split."""
    src = _read()
    selection_map_decl = _extract(
        src, r"const _selectionByPanel\s*=\s*new WeakMap\(\);", "_selectionByPanel declaration"
    )
    selection_for_fn = _extract(
        src, r"function _selectionFor\(panel\)\s*\{.*?\n\}\n", "_selectionFor"
    )
    update_bulk_bar_fn = _extract(
        src, r"function _updateBulkBar\(panel\)\s*\{.*?\n\}\n", "_updateBulkBar"
    )
    selected_row_card_fn = _extract(
        src, r"function _selectedRowCard\(panel, id\)\s*\{.*?\n\}\n", "_selectedRowCard"
    )
    set_bulk_busy_fn = _extract(
        src, r"function _setBulkBusy\(panel, busy\)\s*\{.*?\n\}\n", "_setBulkBusy"
    )
    disable_row_fn = _extract(src, r"function _disableRow\(card\)\s*\{.*?\n\}\n", "_disableRow")
    fade_out_row_fn = _extract(src, r"function _fadeOutRow\(card\)\s*\{.*?\n\}\n", "_fadeOutRow")
    cache_decl = _extract(
        src, r"let _lastBulkDeclineReason\s*=\s*'';", "_lastBulkDeclineReason declaration"
    )
    on_bulk_decline_fn = "async " + "function _onBulkDecline(panel) {" + _find_function(
        src, "_onBulkDecline"
    ) + "\n}\n"

    script = textwrap.dedent(f"""
        const promptCalls = [];
        async function styledPrompt(message, opts) {{
          promptCalls.push(opts.defaultValue || '');
          return promptCalls.length === 1 ? 'too junior for these' : opts.defaultValue;
        }}
        const toasts = [];
        function showToast(msg) {{ toasts.push(msg); }}

        // A single fake panel: querySelector is only ever asked for elements
        // this test doesn't need to inspect, so null is fine everywhere —
        // every call site already guards with `if (el) ...`.
        const panel = {{ querySelector: () => null }};
        // _selectedRowCard optionally uses window.CSS.escape(id); plain node
        // has no `window`, so stub the one property it feature-detects.
        globalThis.window = {{ CSS: undefined }};

        let apiCallCount = 0;
        async function _api(path, opts) {{
          apiCallCount += 1;
          // First-ever call (row-1 on the first attempt) fails; every other
          // call (row-2 on the first attempt, and row-1's retry) succeeds.
          if (apiCallCount === 1) {{
            const e = new Error('That did not go through (error 500).');
            e.status = 500;
            throw e;
          }}
          return {{ ok: true }};
        }}

        {selection_map_decl}
        {selection_for_fn}
        {update_bulk_bar_fn}
        {selected_row_card_fn}
        {set_bulk_busy_fn}
        {disable_row_fn}
        {fade_out_row_fn}
        {cache_decl}
        {on_bulk_decline_fn}

        (async () => {{
          const sel = _selectionFor(panel);
          sel.add('row-1');
          sel.add('row-2');

          await _onBulkDecline(panel);   // row-1 fails, row-2 succeeds
          const afterFirstBatch = _lastBulkDeclineReason;
          const stillSelected = Array.from(_selectionFor(panel));

          await _onBulkDecline(panel);   // retry: only row-1 left, succeeds
          const afterRetry = _lastBulkDeclineReason;

          console.log(JSON.stringify({{
            promptCalls, toasts, afterFirstBatch, stillSelected, afterRetry, apiCallCount,
          }}));
        }})();
    """)
    out = _run_node(script)

    assert out["promptCalls"][0] == "", "the first-ever batch attempt has nothing to prefill"
    assert out["afterFirstBatch"] == "too junior for these", (
        "the shared reason must be preserved once the batch had at least one failure"
    )
    assert out["stillSelected"] == ["row-1"], (
        "the row that succeeded must drop out of the selection; the failed row stays"
    )
    assert out["promptCalls"][1] == "too junior for these", (
        "the retry's prompt must be prefilled with the preserved reason, not blank"
    )
    assert out["afterRetry"] == "", (
        "once every remaining row in the batch succeeds, the cache must be cleared again"
    )
    assert out["apiCallCount"] == 3
