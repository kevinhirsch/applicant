"""Regression coverage for the Debug modal's "24/7 loop observability" wiring
(dark-engine audit B7 items #64 / #71 / #73 / #75).

The engine already computed/persisted all four of these; the gap was purely
front-end (or, for #64, a scheduled tick returning before anything was
persisted at all — see ``tests/unit/test_agent_loop.py``'s
``test_gated_tick_persists_a_plain_language_skip_reason``):

* #64 — a scheduled tick that stops before starting new work (paused / waiting
  on setup) now persists a plain-language "why nothing happened" reason
  (``AgentLoop._record_skip_reason``) that the Run controls tab's "What the
  agent is doing" card surfaces, re-headed to "Why nothing's happening right
  now" when it's a skip rather than active narration.
* #71 — ``GET /api/admin/workspace-bridge`` (new engine endpoint + proxy) is
  rendered as a new "Background connection" Config sub-section.
* #73 — the scheduler's per-campaign tick failures/overlap-skips
  (``Scheduler.campaign_health``) are merged into the SAME run-status payload
  the status chip already reads (``scheduler.campaign``) and rendered there.
* #75 — every tick's persisted per-run stats (already returned by the ops
  ``GET /runs/{campaign_id}`` proxy) are now rendered as a "Recent runs"
  mini-table instead of only ever reading ``items[0]`` for config defaults.

Follows the ``test_applicant_detections_stealth_panels_ui.py`` convention:
source-text regex/substring assertions against the browser-only module (no
DOM-independent entry point cheap enough to shim here), plus a syntax smoke.
Each assertion was verified, by hand, to go red against a file-copy backup of
the pre-change ``applicantDebug.js`` (``cp`` — never ``git stash``, which is
shared across worktrees) and green again after restoring.
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKSPACE_DIR = REPO_ROOT / "workspace"
DEBUG_JS = WORKSPACE_DIR / "static" / "js" / "applicantDebug.js"

_HAS_NODE = shutil.which("node") is not None


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def node_available():
    if not _HAS_NODE:
        pytest.skip("node binary not on PATH")


def _extract_fn(src: str, signature: str) -> str:
    m = re.search(re.escape(signature) + r" \{.*?\n\}\n", src, re.S)
    assert m, f"expected a function with signature: {signature!r}"
    return m.group(0)


# ── #64: why nothing happened right now ─────────────────────────────────────


def test_skip_reason_labels_table_covers_the_gating_reasons():
    src = _read(DEBUG_JS)
    labels = re.search(r"const _SKIP_REASON_LABELS = \{.*?\n\};\n", src, re.S)
    assert labels, "expected a machine skip-reason -> plain-language label table"
    body = labels.group(0)
    assert "automated_work_gated" in body
    assert "run_mode_stop" in body
    assert "budget_exhausted" in body


def test_run_now_toast_reuses_the_shared_skip_reason_labels():
    """The 'Run now' result toast must reuse the SAME table, not a second
    hand-maintained copy, so a machine reason always reads the same way."""
    src = _read(DEBUG_JS)
    body = _extract_fn(src, "async function _renderRun()")
    assert "_SKIP_REASON_LABELS[res.reason]" in body


def test_render_run_reheads_the_card_when_the_latest_run_was_a_skip():
    src = _read(DEBUG_JS)
    body = _extract_fn(src, "async function _renderRun()")
    assert "latest_stats" in body
    assert "skip_reason" in body
    assert "Why nothing" in body


# ── #71: engine <-> workspace bridge health ─────────────────────────────────


def test_bridge_renderer_exists_and_fetches_the_admin_proxy():
    src = _read(DEBUG_JS)
    body = _extract_fn(src, "async function _renderBridge(host)")
    assert "${ADMIN}/workspace-bridge" in body
    assert "_fetchJSON(" in body


def test_bridge_renderer_renders_real_config_and_reachability_not_fabricated():
    src = _read(DEBUG_JS)
    body = _extract_fn(src, "async function _renderBridge(host)")
    assert "data.configured" in body
    assert "data.reachable" in body
    assert "_renderOffline(" in body


def test_bridge_renderer_is_engine_wide_not_campaign_scoped():
    """Mirrors Stealth/Diagnostics/Update: process-global, no campaign guard."""
    src = _read(DEBUG_JS)
    body = _extract_fn(src, "async function _renderBridge(host)")
    assert "_needCampaign" not in body


def test_bridge_panel_is_wired_as_a_config_subsection_not_a_new_tab():
    src = _read(DEBUG_JS)
    body = _extract_fn(src, "async function _renderConfig()")
    assert "applicant-config-bridge" in body
    assert "_renderBridge" in body
    assert "wireRetry(sectionHost" in body
    tabs = re.search(r"const TABS = \[.*?\];\n", src, re.S)
    assert tabs
    assert "bridge" not in tabs.group(0)


def test_bridge_renderer_avoids_upstream_jargon():
    src = _read(DEBUG_JS)
    body = _extract_fn(src, "async function _renderBridge(host)")
    assert not re.search(r"\bFR-[A-Z]+-\d+\b", body)
    assert not re.search(r"\bNFR-[A-Z]+-\d+\b", body)


# ── #73: per-campaign tick failures / overlap-skips ─────────────────────────


def test_status_chip_surfaces_this_campaigns_tick_health():
    src = _read(DEBUG_JS)
    body = _extract_fn(src, "function _statusChip(status)")
    assert "sched.campaign" in body
    assert "failure_count" in body
    assert "skipped_count" in body


# ── #75: recent runs mini-table ─────────────────────────────────────────────


def test_recent_runs_card_exists_and_renders_real_stats():
    src = _read(DEBUG_JS)
    body = _extract_fn(src, "function _recentRunsCard(items)")
    assert "r.stats" in body or "_runStatLine(r.stats)" in body
    assert "esc(" in body


def test_run_stat_line_covers_the_persisted_stat_vocabulary():
    src = _read(DEBUG_JS)
    body = _extract_fn(src, "function _runStatLine(stats)")
    for field in (
        "discovered", "digest_rows", "pipelines_started", "handoffs", "completed",
    ):
        assert f"stats.{field}" in body
    assert "skip_reason" in body


def test_render_run_wires_the_recent_runs_card_from_the_real_items():
    src = _read(DEBUG_JS)
    body = _extract_fn(src, "async function _renderRun()")
    assert "_recentRunsCard(runs.items" in body


# ── syntax smoke ─────────────────────────────────────────────────────────────


def test_node_check_applicant_debug_js(node_available):
    res = subprocess.run(
        ["node", "--check", str(DEBUG_JS)],
        capture_output=True,
        timeout=15,
        text=True,
    )
    assert res.returncode == 0, f"node --check failed:\n{res.stderr}"
