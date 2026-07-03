"""Regression coverage for dark-engine audit item #63: render the scheduler's
loop-health metrics that already reach the browser.

The engine already packs operational metrics (tick totals, success/failure
counts, the consecutive-failure streak, and whether the stall alert is
currently armed — ``observability/metrics.py``'s ``Metrics.snapshot()``) into
BOTH:

* the read-only status proxy's ``scheduler`` block (``scheduler.state()``
  verbatim, via ``routers/agent_runs.py``'s ``run_status`` -> workspace's
  ``GET /api/applicant/activity/status``), and
* the consolidated snapshot's ``now.metrics`` (``routers/agent_status.py`` ->
  workspace's ``GET /api/applicant/activity/snapshot``).

Both proxies (``workspace/routes/applicant_activity_routes.py``) already pass
the engine payload through UNMODIFIED — confirmed by reading the route bodies,
neither strips fields — so this was a pure render gap: nothing in
``static/js/applicantActivity.js`` looked past ``scheduler.running``. This
file pins the fix: a plain-language health chip ("312 runs · no failures
yet") plus a visible stall warning, rendered in the Activity modal's "Agent
status" card (``_renderSnapshot``), with no jargon and no fabricated numbers.

Follows the source-text-regex convention used by
``test_applicant_round2_emailscan_ui.py`` / ``test_applicant_round1_observability.py``
for this browser-only module (top-level ``_boot()`` runs on import, so it's
not importable under a bare ``node --input-type=module`` without a DOM shim).

Every assertion below was hand-verified to go RED when the corresponding
piece of the fix is reverted (temporarily reintroducing the pre-fix
``_renderSnapshot`` body / deleting the new helper functions), then restored
to GREEN.
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
AGENT_STATUS_PY = REPO_ROOT / "src" / "applicant" / "app" / "routers" / "agent_status.py"
AGENT_RUNS_PY = REPO_ROOT / "src" / "applicant" / "app" / "routers" / "agent_runs.py"

_HAS_NODE = shutil.which("node") is not None


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _top_level_fn(src: str, name: str) -> str:
    """Extract a top-level `function name(...) { ... }` body (same convention
    as ``test_applicant_round1_observability.py``'s helper)."""
    m = re.search(rf"function {re.escape(name)}\([^)]*\)\s*\{{(.*?)\n\}}", src, re.S)
    assert m, f"expected a top-level function {name}(...)"
    return m.group(1)


@pytest.fixture(scope="module")
def node_available():
    if not _HAS_NODE:
        pytest.skip("node binary not on PATH")


# ── proxy pass-through: confirm no proxy fix was needed ─────────────────────


def test_status_proxy_does_not_strip_the_scheduler_block():
    """``/api/applicant/activity/status`` must forward the engine's full
    payload (including ``scheduler`` -> ``metrics``) unmodified: it only
    ``setdefault``s/sets a few of its OWN fields, never pops/rebuilds
    ``scheduler``."""
    src = _read(ACTIVITY_ROUTES_PY)
    fn = re.search(
        r"async def activity_status\(request: Request\) -> dict:.*?\n        return out\n",
        src,
        re.S,
    )
    assert fn, "expected the activity_status route handler"
    body = fn.group(0)
    assert "out = data if isinstance(data, dict) else {}" in body
    assert '"scheduler"' not in body, (
        "the status proxy must not touch the scheduler field at all -- "
        "it is passed through verbatim from the engine payload"
    )


def test_snapshot_proxy_does_not_strip_the_now_block():
    """``/api/applicant/activity/snapshot`` must forward the engine's
    consolidated ``now``/``next``/``recent`` payload unmodified too."""
    src = _read(ACTIVITY_ROUTES_PY)
    fn = re.search(
        r"async def activity_snapshot\(request: Request\) -> dict:.*?\n        return out\n",
        src,
        re.S,
    )
    assert fn, "expected the activity_snapshot route handler"
    body = fn.group(0)
    assert "out = data if isinstance(data, dict) else {}" in body
    assert '"now"' not in body, (
        "the snapshot proxy must not touch the now/next/recent fields -- "
        "passed through verbatim from the engine payload"
    )


def test_engine_scheduler_state_already_carries_a_metrics_block():
    """Pin the engine-side source of truth this chip renders: the scheduler
    status route (``agent_runs.py``) assigns the FULL ``scheduler.state()``
    (which nests ``metrics``) onto the response, and the consolidated status
    route (``agent_status.py``) also surfaces the same metrics dict under
    ``now.metrics`` -- both already reach the browser through the untouched
    proxies above."""
    runs_src = _read(AGENT_RUNS_PY)
    assert 'out["scheduler"] = scheduler.state()' in runs_src

    status_src = _read(AGENT_STATUS_PY)
    assert 'metrics = sched.get("metrics")' in status_src
    assert 'now_block["metrics"] = metrics' in status_src


# ── the new helpers: read metrics from either payload shape ─────────────────


def test_loop_metrics_helper_reads_either_payload_shape():
    src = _read(ACTIVITY_JS)
    fn = _top_level_fn(src, "_loopMetrics")
    assert "data.now" in fn and "data.now.metrics" in fn
    assert "data.scheduler" in fn and "data.scheduler.metrics" in fn


def test_health_chip_text_reports_no_failures_yet_when_clean():
    src = _read(ACTIVITY_JS)
    fn = _top_level_fn(src, "_healthChipText")
    assert "ticks_total" in fn
    assert "ticks_failed" in fn
    assert "no failures yet" in fn


def test_health_chip_text_uses_relative_time_for_a_recent_failure():
    """When the LAST tick itself failed, the chip should read '... last
    failure <relative time> ago' -- reusing the existing ``_relTime`` helper
    (no hand-rolled date math)."""
    src = _read(ACTIVITY_JS)
    fn = _top_level_fn(src, "_healthChipText")
    assert "last_tick_success === false" in fn
    assert "last_heartbeat" in fn
    assert "_relTime(" in fn
    assert "last failure" in fn


def test_health_warning_text_only_fires_when_alerting_is_armed():
    src = _read(ACTIVITY_JS)
    fn = _top_level_fn(src, "_healthWarningText")
    assert "m.alerting" in fn
    assert "return ''" in fn, "expected an early-out when the stall alert is not armed"
    assert "consecutive_failures" in fn
    assert "Stalled" in fn


def test_health_texts_carry_no_engine_jargon():
    """White-label: the plain-language strings themselves must not leak raw
    engine field names or FR-/NFR- jargon to the user."""
    src = _read(ACTIVITY_JS)
    chip_fn = _top_level_fn(src, "_healthChipText")
    warn_fn = _top_level_fn(src, "_healthWarningText")
    for fn_body, label in ((chip_fn, "_healthChipText"), (warn_fn, "_healthWarningText")):
        for banned in ("FR-", "NFR-", "consecutive_failure_alert", "tick_ok"):
            assert banned not in fn_body, f"{label} leaks jargon: {banned!r}"


# ── wired into the visible snapshot card ────────────────────────────────────


def test_render_snapshot_renders_the_health_chip_and_warning():
    src = _read(ACTIVITY_JS)
    fn = _top_level_fn(src, "_renderSnapshot")
    assert "_loopMetrics(data)" in fn
    assert "_healthChipText(" in fn
    assert "_healthWarningText(" in fn
    # Escaped, not raw-injected -- consistent with every other dynamic string
    # in this card (_snapshotLine already does `esc(...)`).
    assert "esc(chipText)" in fn
    assert "esc(warnText)" in fn


def test_render_snapshot_health_chip_contributes_to_the_parts_guard():
    """The chip/warning must be pushed onto the SAME `parts` array the
    Now/Up-next lines use, so the existing `if (!parts.length)` empty-guard
    still governs whether anything renders at all -- a metrics-only payload
    (no now/next sentence) must still show the chip, not blank the card."""
    src = _read(ACTIVITY_JS)
    fn = _top_level_fn(src, "_renderSnapshot")
    # The metrics block must appear before the `if (!parts.length)` guard.
    metrics_idx = fn.index("_loopMetrics(data)")
    guard_idx = fn.index("if (!parts.length)")
    assert metrics_idx < guard_idx
    assert "parts.push(" in fn[metrics_idx:guard_idx]


def test_health_warning_uses_a_css_var_not_a_hardcoded_hex_only():
    """Reuse the existing warm-warning token pattern already used elsewhere
    in the app (``var(--orange, #ffb86c)``) rather than inventing a bespoke
    class -- consistent with the do-not-invent-CSS-classes constraint."""
    src = _read(ACTIVITY_JS)
    fn = _top_level_fn(src, "_renderSnapshot")
    assert "var(--orange, #ffb86c)" in fn


# ── syntax smoke ─────────────────────────────────────────────────────────────


def test_node_check_applicant_activity_js(node_available):
    res = subprocess.run(
        ["node", "--check", str(ACTIVITY_JS)],
        capture_output=True,
        timeout=15,
        text=True,
    )
    assert res.returncode == 0, f"node --check failed:\n{res.stderr}"
