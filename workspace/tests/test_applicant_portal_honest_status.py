"""Product-honesty: the Portal home base must NEVER claim it's "searching" while
the engine's own apply-readiness gate is closed (CRIT gate-fix).

These drive the REAL ``applicantPortal.js`` render seam under node: the gate-aware
``_renderVacant`` picks the honest "your search isn't running yet — here's what's
left" state when the gate is closed and the calm "Searching…" state ONLY when the
gate is genuinely open (or unknown, where we degrade to today's calm state rather
than a false alarm). Zero network — the functions are sliced out and exercised
directly with stubbed leaf deps.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
PORTAL_JS = _REPO / "static" / "js" / "applicantPortal.js"
_HAS_NODE = shutil.which("node") is not None


@pytest.fixture(scope="module")
def node_available():
    if not _HAS_NODE:
        pytest.skip("node binary not on PATH")


def _slice_between(src: str, start_marker: str, end_marker: str) -> str:
    start = src.index(start_marker)
    end = src.index(end_marker, start)
    return src[start:end]


def _honest_status_block() -> str:
    """The gate helpers + the gate-aware vacant/empty/not-running renderers."""
    src = PORTAL_JS.read_text(encoding="utf-8")
    helpers = _slice_between(src, "function _searchRunning()", "async function _confirm(")
    renderers = _slice_between(src, "function _renderEmpty(body) {", "// ── Row rendering")
    return helpers + "\n" + renderers


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


def _drive(gate: dict) -> dict:
    block = _honest_status_block()
    script = (
        """
        // Leaf-dep stubs — identity esc so substring checks are exact.
        const esc = (s) => String(s == null ? '' : s);
        const _neverDoesHTML = () => '';
        const _agentPulseLine = () => 'Searching and preparing applications for you';
        const _toast = () => {};
        const _close = () => {};
        const window = {};
        const bodyEl = {
          innerHTML: '',
          querySelector: () => ({ addEventListener: () => {} }),
        };
        let _gate = __GATE__;

        __BLOCK__

        _renderVacant(bodyEl);
        console.log(JSON.stringify({
          html: bodyEl.innerHTML,
          searchRunning: _searchRunning(),
          gateClosed: _gateClosed(),
        }));
        """
        .replace("__GATE__", json.dumps(gate))
        .replace("__BLOCK__", block)
    )
    return _run_node(script)


_SEARCHING = "Searching and preparing applications for you"
_NOT_RUNNING = "Your search isn't running yet"


def test_gate_closed_shows_not_running_with_whats_left(node_available):
    out = _drive({
        "automated_work_allowed": False,
        "apply_ready": False,
        "apply_missing": ["salary floor", "a résumé"],
    })
    assert out["gateClosed"] is True
    assert out["searchRunning"] is False
    # Honest: names the not-running state + the exact server-truth apply_missing…
    assert _NOT_RUNNING in out["html"]
    assert "salary floor" in out["html"]
    assert "a résumé" in out["html"]
    # …and NEVER the green "I'm searching" claim while the gate is closed.
    assert _SEARCHING not in out["html"]


def test_gate_open_shows_active_searching(node_available):
    out = _drive({
        "automated_work_allowed": True,
        "apply_ready": True,
        "apply_missing": [],
    })
    assert out["searchRunning"] is True
    assert out["gateClosed"] is False
    # Only when the gate is genuinely open do we show the active "searching" state.
    assert _SEARCHING in out["html"]
    assert _NOT_RUNNING not in out["html"]


def test_gate_unknown_degrades_to_calm_state(node_available):
    # An older engine / failed status read leaves the gate unknown (null). We must
    # NOT raise a false "not running" alarm — degrade to today's calm empty state.
    out = _drive({
        "automated_work_allowed": None,
        "apply_ready": None,
        "apply_missing": [],
    })
    assert out["gateClosed"] is False
    assert out["searchRunning"] is False  # unknown is not "running" either
    assert _SEARCHING in out["html"]
    assert _NOT_RUNNING not in out["html"]
