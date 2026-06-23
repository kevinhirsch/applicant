"""Pin the pure view helpers in static/js/applicantUpdateView.js — the Update
modal's state→message mapping (`updateStateView`) and log formatter
(`formatLogTail`). Driven through `node --input-type=module` so we get real
JS execution without a Vitest/Jest setup; skips itself if `node` is absent.

These helpers live in a dependency-free leaf module (no DOM / fetch / ./ui.js)
precisely so they can be unit-tested here without the browser-only module graph
that applicantUpdate.js pulls in. The DOM-coupled render/poll/launcher wiring in
applicantUpdate.js is covered by the front-door Playwright/monkey crawl, not this
suite.
"""

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_HAS_NODE = shutil.which("node") is not None


@pytest.fixture(scope="module")
def node_available():
    if not _HAS_NODE:
        pytest.skip("node binary not on PATH")


def _run_node(script: str) -> dict:
    res = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=_REPO,
        capture_output=True,
        timeout=15,
        text=True,
    )
    if res.returncode != 0:
        raise AssertionError(f"node failed:\n{res.stderr}")
    out_lines = [ln for ln in res.stdout.splitlines() if ln.strip()]
    if not out_lines:
        raise AssertionError("node produced no stdout")
    return json.loads(out_lines[-1])


# ── updateStateView ────────────────────────────────────────────────

def test_state_view_engine_offline(node_available):
    """engine_available=false short-circuits to the offline view with no
    trigger button, regardless of any other field."""
    script = textwrap.dedent("""
        const { updateStateView } = await import('./static/js/applicantUpdateView.js');
        const v = updateStateView({ engine_available: false, state: 'running' });
        console.log(JSON.stringify({ kind: v.kind, canTrigger: v.canTrigger, running: v.running }));
    """)
    out = _run_node(script)
    assert out == {"kind": "offline", "canTrigger": False, "running": False}


def test_state_view_no_updater(node_available):
    """updater_available=false → a plain note (no dead button), even though
    the engine is up. canTrigger must be false so no button renders."""
    script = textwrap.dedent("""
        const { updateStateView } = await import('./static/js/applicantUpdateView.js');
        const v = updateStateView({ engine_available: true, updater_available: false, state: 'idle' });
        console.log(JSON.stringify({ kind: v.kind, canTrigger: v.canTrigger }));
    """)
    out = _run_node(script)
    assert out == {"kind": "no-updater", "canTrigger": False}


def test_state_view_running_disables_trigger(node_available):
    """state=running → running view with canTrigger=false so the
    "Update now" button is disabled while an update is in flight."""
    script = textwrap.dedent("""
        const { updateStateView } = await import('./static/js/applicantUpdateView.js');
        const v = updateStateView({ engine_available: true, state: 'running' });
        console.log(JSON.stringify({ kind: v.kind, running: v.running, canTrigger: v.canTrigger }));
    """)
    out = _run_node(script)
    assert out == {"kind": "running", "running": True, "canTrigger": False}


def test_state_view_terminal_and_idle(node_available):
    """success/failed/idle are all re-triggerable (canTrigger=true); an
    absent/unknown state falls back to the idle ready-to-update view."""
    script = textwrap.dedent("""
        const { updateStateView } = await import('./static/js/applicantUpdateView.js');
        const kinds = {};
        for (const st of ['success', 'failed', 'idle']) {
          const v = updateStateView({ engine_available: true, state: st });
          kinds[st] = { kind: v.kind, canTrigger: v.canTrigger };
        }
        // Missing state defaults to idle.
        const u = updateStateView({ engine_available: true });
        kinds['missing'] = { kind: u.kind, canTrigger: u.canTrigger };
        // Wholly absent payload must not throw and must degrade to idle.
        const e = updateStateView();
        kinds['empty'] = { kind: e.kind, canTrigger: e.canTrigger };
        console.log(JSON.stringify(kinds));
    """)
    out = _run_node(script)
    assert out == {
        "success": {"kind": "success", "canTrigger": True},
        "failed": {"kind": "failed", "canTrigger": True},
        "idle": {"kind": "idle", "canTrigger": True},
        "missing": {"kind": "idle", "canTrigger": True},
        "empty": {"kind": "idle", "canTrigger": True},
    }


def test_state_view_uses_engine_message(node_available):
    """When the engine supplies a message, the view surfaces it verbatim
    (the user sees the engine's own words, not a canned string)."""
    script = textwrap.dedent("""
        const { updateStateView } = await import('./static/js/applicantUpdateView.js');
        const v = updateStateView({ engine_available: true, state: 'failed', message: 'disk full' });
        console.log(JSON.stringify({ message: v.message }));
    """)
    out = _run_node(script)
    assert out == {"message": "disk full"}


# ── formatLogTail ──────────────────────────────────────────────────

def test_format_log_tail(node_available):
    """Strings join one-per-line (trailing whitespace trimmed); objects are
    JSON-stringified; an empty/absent tail yields '' so the block is hidden."""
    script = textwrap.dedent("""
        const { formatLogTail } = await import('./static/js/applicantUpdateView.js');
        console.log(JSON.stringify({
          lines: formatLogTail(['fetching   ', 'building', 'done']),
          object: formatLogTail([{ step: 'x' }]),
          empty: formatLogTail([]),
          absent: formatLogTail(undefined),
          not_array: formatLogTail('nope'),
        }));
    """)
    out = _run_node(script)
    assert out["lines"] == "fetching\nbuilding\ndone"
    assert out["object"] == '{"step":"x"}'
    assert out["empty"] == ""
    assert out["absent"] == ""
    assert out["not_array"] == ""
