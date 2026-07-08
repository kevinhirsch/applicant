"""H1 — receipts, not narration (front-door half).

Phase 1.5's first honesty invariant: every user-facing claim about work done
is a projection of RECORDED actions and links to its receipt — never a model
describing what it thinks it did. The engine half (the claim-path audit pins)
lives in ``tests/unit/test_h1_receipts_not_narration.py``; this file pins the
two front-door receipt affordances:

* **Activity page** (``applicantActivity.js``): each run row now carries an
  expandable per-run receipt (``_receiptHTML``) rendering the RECORDED run
  record's own numbers — the exact ``agent_runs.stats`` counters the row's
  sentence and stat summary were computed from. Honesty rules pinned here:
  a counter the record doesn't carry contributes NO line (no fabricated
  zeros), and a run with no recorded numbers renders NO receipt at all
  (the absence of a record must never render as one).
* **Today** (``applicantToday.js``): the "Today: N applications …" guardrails
  line is computed from the same recorded runs, so the claim now links to its
  receipt — activating it opens Activity (the recorded-run trail).

These follow the repo's sliced-source harness pattern (see
``test_applicant_activity_intent_history.py``): the tests extract the REAL
shipped function bodies and execute them headlessly, so reverting the feature
changes the extracted text itself and the assertions go red.
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
JS_DIR = REPO_ROOT / "workspace" / "static" / "js"
ACTIVITY_JS = JS_DIR / "applicantActivity.js"
TODAY_JS = JS_DIR / "applicantToday.js"

_HAS_NODE = shutil.which("node") is not None


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _top_level_fn(src: str, name: str) -> str:
    """The full source of a top-level ``function name(...) { ... }`` (brace-balanced)."""
    marker = f"function {name}("
    start = src.find(marker)
    assert start != -1, f"expected a top-level function {name}(...)"
    brace = src.index("{", start)
    depth = 0
    for i in range(brace, len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[start : i + 1]
    raise AssertionError(f"unbalanced braces in {name}")


def _node(harness: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["node", "--input-type=commonjs", "-e", harness],
        capture_output=True,
        timeout=15,
        text=True,
    )


_RECEIPT_PRELUDE = """
const esc = (s) => (s == null ? '' : String(s));
function _runTime(run) { return run.timestamp || ''; }
"""


def _receipt_harness(extra: str) -> str:
    src = _read(ACTIVITY_JS)
    labels = re.search(r"const _SKIP_REASON_LABELS = \{.*?\};", src, re.S)
    assert labels, "expected the _SKIP_REASON_LABELS table"
    fn = _top_level_fn(src, "_receiptHTML")
    return _RECEIPT_PRELUDE + labels.group(0) + "\n" + fn + "\n" + extra


# ── Activity: the per-run receipt ────────────────────────────────────────────


def test_activity_run_rows_compose_the_receipt():
    """``_renderRuns`` renders ``_receiptHTML(run)`` into every row."""
    body = _top_level_fn(_read(ACTIVITY_JS), "_renderRuns")
    assert "_receiptHTML(run)" in body, (
        "expected each Activity run row to carry its recorded-run receipt"
    )


def test_receipt_renders_only_the_recorded_counters():
    """A full stats block renders each recorded number; the labels are plain
    language; and the recorded timestamp closes the receipt."""
    if not _HAS_NODE:
        pytest.skip("node binary not on PATH")
    harness = _receipt_harness(
        """
    const html = _receiptHTML({
      timestamp: '2026-07-08T09:00:00Z',
      stats: {
        discovered: 5, digest_rows: 3, pipelines_started: 2, handoffs: 1,
        completed: 1, budget_remaining: 9, llm_calls: 12, cost_usd_estimate: 0.42,
      },
    });
    for (const needle of ['Roles found', '5', 'Shortlisted for you', '3',
        'Applications started', '2', 'Handed to you', 'Submitted',
        'Model calls', '12', '~$0.42', '2026-07-08T09:00:00Z', '<details']) {
      if (!html.includes(needle)) throw new Error('missing ' + needle + ' in: ' + html);
    }
    console.log('OK');
    """
    )
    res = _node(harness)
    assert res.returncode == 0, f"stdout={res.stdout}\nstderr={res.stderr}"
    assert "OK" in res.stdout


def test_receipt_omits_counters_the_record_does_not_carry():
    """An absent counter contributes no line — the receipt never pads itself
    with zeros the run didn't record (H1: no fabricated numbers)."""
    if not _HAS_NODE:
        pytest.skip("node binary not on PATH")
    harness = _receipt_harness(
        """
    const html = _receiptHTML({
      timestamp: '2026-07-08T09:00:00Z',
      stats: { discovered: 4 },
    });
    if (!html.includes('Roles found')) throw new Error('expected the recorded counter');
    for (const absent of ['Submitted', 'Model calls', 'Estimated model cost',
        'Applications started', 'budget']) {
      if (html.includes(absent)) throw new Error('fabricated line: ' + absent + ' in: ' + html);
    }
    console.log('OK');
    """
    )
    res = _node(harness)
    assert res.returncode == 0, f"stdout={res.stdout}\nstderr={res.stderr}"
    assert "OK" in res.stdout


def test_no_recorded_numbers_means_no_receipt_at_all():
    """A run with nothing recorded renders NO receipt — an empty shell would
    read as a receipt that isn't there (the absence of a check must never
    render as a check)."""
    if not _HAS_NODE:
        pytest.skip("node binary not on PATH")
    harness = _receipt_harness(
        """
    for (const run of [null, {}, { stats: {} },
        { timestamp: '2026-07-08T09:00:00Z', stats: {} },
        { stats: { discovered: 0, completed: 0 } }]) {
      const html = _receiptHTML(run);
      if (html !== '') throw new Error('expected no receipt, got: ' + html);
    }
    console.log('OK');
    """
    )
    res = _node(harness)
    assert res.returncode == 0, f"stdout={res.stdout}\nstderr={res.stderr}"
    assert "OK" in res.stdout


def test_receipt_translates_the_skip_reason_to_plain_language():
    """A recorded no-new-work run shows WHY in plain words (white-label: no
    machine tokens where a mapping exists; unknown tokens still show the raw
    recorded value rather than hiding it)."""
    if not _HAS_NODE:
        pytest.skip("node binary not on PATH")
    harness = _receipt_harness(
        """
    const known = _receiptHTML({ stats: { skip_reason: 'automated_work_gated' } });
    if (!known.includes('waiting on setup')) throw new Error('expected plain language: ' + known);
    if (known.includes('automated_work_gated')) throw new Error('machine token leaked: ' + known);
    const unknown = _receiptHTML({ stats: { skip_reason: 'zz_other' } });
    if (!unknown.includes('zz_other')) throw new Error('raw value hidden: ' + unknown);
    console.log('OK');
    """
    )
    res = _node(harness)
    assert res.returncode == 0, f"stdout={res.stdout}\nstderr={res.stderr}"
    assert "OK" in res.stdout


# ── Today: the guardrails count links to its receipt (Activity) ──────────────


def test_today_guardrails_line_opens_activity_as_its_receipt():
    src = _read(TODAY_JS)
    # Wired once in the modal scaffold…
    assert "openApplicantActivity" in src, (
        "expected the Today guardrails line to open Activity (its receipt trail)"
    )
    # …and made an announced, keyboard-operable affordance when populated.
    fn = _top_level_fn(src, "_loadGuardrails")
    assert "recorded runs" in fn, "expected the receipt tooltip on the guardrails line"
    assert "setAttribute('role', 'button')" in fn
    assert "setAttribute('tabindex', '0')" in fn


def test_today_guardrails_receipt_affordance_disarms_when_cleared():
    """A cleared/hidden guardrails line must not stay focusable as a link."""
    fn = _top_level_fn(_read(TODAY_JS), "_loadGuardrails")
    assert "removeAttribute('role')" in fn
    assert "removeAttribute('tabindex')" in fn


# ── node --check (CI-equivalent syntax gate on both touched files) ───────────


@pytest.mark.parametrize("path", [ACTIVITY_JS, TODAY_JS])
def test_node_check_touched_js(path):
    if not _HAS_NODE:
        pytest.skip("node binary not on PATH")
    res = subprocess.run(
        ["node", "--check", str(path)],
        capture_output=True,
        timeout=15,
        text=True,
    )
    assert res.returncode == 0, f"node --check failed for {path.name}:\n{res.stderr}"
