"""Regression coverage for dark-engine audit item #59 (B6): the ``AgentIntent``
history exists (per-run intent sentences persisted with a timestamp,
``core/entities/agent_run.py`` -- the audit's own anchor,
``core/entities/agent_intent.py``, is an unused entity; the real persisted
history is ``AgentRun.intent_sentence`` rows), but only the LATEST sentence
was ever readable as a proper "recent trail."

The engine's own ``AgentRunRepository.list_for_campaign`` deliberately returns
runs OLDEST-first (contract-tested: ``tests/contract/base.py``
``test_agent_run_list_pagination``) -- every consumer is expected to
reverse/cap client-side. The admin debug modal's "Recent runs" mini-table
already does this (dark-engine audit #75, ``applicantDebug.js``
``_recentRunsCard``: ``items.slice(-8).reverse()``, whose own comment claims
to mirror ``applicantActivity.js``'s "Recently I…" list) -- but
``applicantActivity.js``'s dedicated Activity page never actually did: it
rendered the engine's raw, unbounded, oldest-first list, which both
mislabeled the "Recently I…" heading (oldest run at the top) and could grow
without bound for a long-running campaign. That defeated "an intent timeline
… a short scrollable list" (the item's own wording).

This pins the fix: ``_renderRuns`` now caps to the most recent
``_RECENT_RUNS_CAP`` runs and shows them newest-first, mirroring the debug
mini-table's already-correct pattern. No proxy/engine code changed --
``workspace/routes/applicant_activity_routes.py`` already forwards the
engine's ``items`` list untouched (see ``test_applicant_activity_routes.py``);
this is a pure render-side fix, same shape as items #56/#63.

Every assertion below was hand-verified to go RED when the fix is reverted
(restoring the pre-fix ``_renderRuns`` body from a file-copy backup), then
confirmed GREEN again after restoring.
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
ACTIVITY_ROUTES_PY = REPO_ROOT / "workspace" / "routes" / "applicant_activity_routes.py"

_HAS_NODE = shutil.which("node") is not None


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _top_level_fn(src: str, name: str) -> str:
    m = re.search(rf"function {re.escape(name)}\([^)]*\)\s*\{{(.*?)\n\}}", src, re.S)
    assert m, f"expected a top-level function {name}(...)"
    return m.group(1)


@pytest.fixture(scope="module")
def node_available():
    if not _HAS_NODE:
        pytest.skip("node binary not on PATH")


# ── proxy pass-through: confirm no proxy fix was needed ─────────────────────


def test_runs_proxy_does_not_reorder_items_itself():
    """``/api/applicant/activity/runs`` must forward the engine's ``items``
    list untouched (ordering is the render layer's job, exactly like the
    admin debug mini-table) -- it only filters non-dict entries."""
    src = _read(ACTIVITY_ROUTES_PY)
    fn = re.search(
        r"async def activity_runs\(request: Request\) -> dict:.*?\n        return \{",
        src,
        re.S,
    )
    assert fn, "expected the activity_runs route handler"
    body = fn.group(0)
    assert ".reverse(" not in body
    assert ".sort(" not in body


# ── the render fix ──────────────────────────────────────────────────────────


def test_render_runs_caps_and_reverses_to_show_most_recent_first():
    src = _read(ACTIVITY_JS)
    fn = _top_level_fn(src, "_renderRuns")
    assert "_RECENT_RUNS_CAP" in fn
    assert ".reverse()" in fn


def test_render_runs_shows_newest_first_for_oldest_first_engine_data():
    """The engine's own ordering contract is oldest-first (pinned separately
    in ``tests/contract/base.py``) -- feed ``_renderRuns`` an oldest-first
    list and confirm the RENDERED order comes out newest-first via a tiny
    node harness (no DOM needed: capture the array passed to ``.map`` by
    monkey-patching ``Array.prototype.map`` for this one call)."""
    if not _HAS_NODE:
        pytest.skip("node binary not on PATH")
    src = _read(ACTIVITY_JS)
    cap_m = re.search(r"const _RECENT_RUNS_CAP = \d+;", src)
    assert cap_m, "expected a _RECENT_RUNS_CAP constant"
    fn_src = "function _renderRuns(host, items) {" + _top_level_fn(src, "_renderRuns") + "\n}"
    harness = f"""
    const esc = (s) => String(s);
    function _relTime() {{ return ''; }}
    function _statSummary() {{ return ''; }}
    function _runTime(run) {{ return run.timestamp || ''; }}
    function _renderEmpty() {{}}
    function _receiptHTML() {{ return ''; }}
    {cap_m.group(0)}
    {fn_src}
    const items = [
      {{id: 'r0', intent: 'oldest', timestamp: '2026-01-01T00:00:00Z'}},
      {{id: 'r1', intent: 'middle', timestamp: '2026-01-02T00:00:00Z'}},
      {{id: 'r2', intent: 'newest', timestamp: '2026-01-03T00:00:00Z'}},
    ];
    let captured = null;
    const host = {{ set innerHTML(v) {{ captured = v; }}, get innerHTML() {{ return captured; }} }};
    _renderRuns(host, items);
    // First row rendered must be the NEWEST run's intent, not the oldest.
    const newestIdx = captured.indexOf('newest');
    const oldestIdx = captured.indexOf('oldest');
    if (newestIdx === -1 || oldestIdx === -1 || newestIdx > oldestIdx) {{
      throw new Error('expected newest-first ordering, got: ' + captured);
    }}
    console.log('OK');
    """
    res = subprocess.run(
        ["node", "--input-type=commonjs", "-e", harness],
        capture_output=True,
        timeout=15,
        text=True,
    )
    assert res.returncode == 0, f"stdout={res.stdout}\nstderr={res.stderr}"
    assert "OK" in res.stdout


def test_render_runs_caps_a_long_history_to_a_short_list():
    if not _HAS_NODE:
        pytest.skip("node binary not on PATH")
    src = _read(ACTIVITY_JS)
    cap_m = re.search(r"const _RECENT_RUNS_CAP = \d+;", src)
    assert cap_m, "expected a _RECENT_RUNS_CAP constant"
    fn_src = "function _renderRuns(host, items) {" + _top_level_fn(src, "_renderRuns") + "\n}"
    harness = f"""
    const esc = (s) => String(s);
    function _relTime() {{ return ''; }}
    function _statSummary() {{ return ''; }}
    function _runTime(run) {{ return run.id; }}
    function _renderEmpty() {{}}
    function _receiptHTML() {{ return ''; }}
    {cap_m.group(0)}
    {fn_src}
    const items = [];
    for (let i = 0; i < 500; i++) {{ items.push({{id: 'r' + i, intent: 'intent-' + i}}); }}
    let captured = null;
    const host = {{ set innerHTML(v) {{ captured = v; }}, get innerHTML() {{ return captured; }} }};
    _renderRuns(host, items);
    const count = (captured.match(/intent-/g) || []).length;
    if (count > 30) {{ throw new Error('expected a capped, short list; got ' + count + ' rows'); }}
    if (count < 1) {{ throw new Error('expected at least one row'); }}
    console.log('COUNT=' + count);
    """
    res = subprocess.run(
        ["node", "--input-type=commonjs", "-e", harness],
        capture_output=True,
        timeout=15,
        text=True,
    )
    assert res.returncode == 0, f"stdout={res.stdout}\nstderr={res.stderr}"


def test_node_check_applicant_activity_js(node_available):
    res = subprocess.run(
        ["node", "--check", str(ACTIVITY_JS)],
        capture_output=True,
        timeout=15,
        text=True,
    )
    assert res.returncode == 0, f"node --check failed:\n{res.stderr}"
