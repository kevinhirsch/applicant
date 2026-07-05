"""Regression coverage for three new Debug/Config sub-sections (dark-engine
audit B7 items #67 / #72 / #79):

* #67 — the captcha strategy (``CAPTCHA_STRATEGY``) is configurable and the
  composite solver decides avoid/solve/handoff, but no surface showed the
  effective strategy or whether it was doing anything. A new "Captcha
  handling" Config sub-section reads ``GET /api/admin/captcha-status``.
* #72 — ``CapacityService`` admits/defers a sandbox slot every tick (the
  browser-concurrency cap), but nothing showed how many applications hold a
  slot vs. wait. A new "Automation capacity" sub-section reads
  ``GET /api/admin/capacity``.
* #79 — ``LocalEmbedding`` is a deterministic offline hashing-trick backend;
  nothing disclosed that memory/dedup matching quality is the basic offline
  fallback. A new "Matching engine" sub-section reads
  ``GET /api/admin/embedding-backend``.

Follows the ``test_applicant_loop_observability_panels_ui.py`` convention:
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


# ── #67: captcha handling status ────────────────────────────────────────────


def test_captcha_renderer_exists_and_fetches_the_admin_proxy():
    src = _read(DEBUG_JS)
    body = _extract_fn(src, "async function _renderCaptcha(host)")
    assert "${ADMIN}/captcha-status" in body
    assert "_fetchJSON(" in body


def test_captcha_renderer_renders_the_real_strategy_and_activity_not_fabricated():
    src = _read(DEBUG_JS)
    body = _extract_fn(src, "async function _renderCaptcha(host)")
    assert "data.strategy" in body
    assert "data.active" in body
    assert "_renderOffline(" in body


def test_captcha_renderer_only_shows_counters_when_a_solver_is_actually_wired():
    """Must gate the solved/avoided/handed-off numbers on ``data.active`` — never
    render a fabricated zero/blank count for the unwired default."""
    src = _read(DEBUG_JS)
    body = _extract_fn(src, "async function _renderCaptcha(host)")
    assert "data.active && typeof data.attempts" in body


def test_captcha_renderer_is_engine_wide_not_campaign_scoped():
    src = _read(DEBUG_JS)
    body = _extract_fn(src, "async function _renderCaptcha(host)")
    assert "_needCampaign" not in body


def test_captcha_renderer_avoids_upstream_jargon():
    src = _read(DEBUG_JS)
    body = _extract_fn(src, "async function _renderCaptcha(host)")
    assert not re.search(r"\bFR-[A-Z]+-\d+\b", body)
    assert not re.search(r"\bNFR-[A-Z]+-\d+\b", body)
    # The rendered copy itself must be plain language, not the raw env-var name
    # (the lookup TABLE's own identifier legitimately echoes it — check the
    # user-visible strings, not the whole function body).
    rendered_strings = re.findall(r"'([^']*)'", body)
    assert not any("CAPTCHA_STRATEGY" in s for s in rendered_strings)


# ── #72: sandbox capacity pacing ────────────────────────────────────────────


def test_capacity_renderer_exists_and_fetches_the_admin_proxy():
    src = _read(DEBUG_JS)
    body = _extract_fn(src, "async function _renderCapacity(host)")
    assert "${ADMIN}/capacity" in body
    assert "_fetchJSON(" in body


def test_capacity_renderer_renders_real_active_and_waiting_counts():
    src = _read(DEBUG_JS)
    body = _extract_fn(src, "async function _renderCapacity(host)")
    assert "data.active_count" in body
    assert "data.waiting_count" in body
    assert "_renderOffline(" in body


def test_capacity_renderer_handles_the_unsupported_backend_case():
    src = _read(DEBUG_JS)
    body = _extract_fn(src, "async function _renderCapacity(host)")
    assert "data.supported" in body
    assert "_empty(" in body


# ── #79: embedding backend disclosure ───────────────────────────────────────


def test_embedding_renderer_exists_and_fetches_the_admin_proxy():
    src = _read(DEBUG_JS)
    body = _extract_fn(src, "async function _renderEmbedding(host)")
    assert "${ADMIN}/embedding-backend" in body
    assert "_fetchJSON(" in body


def test_embedding_renderer_renders_the_real_backend_and_quality():
    src = _read(DEBUG_JS)
    body = _extract_fn(src, "async function _renderEmbedding(host)")
    assert "data.model_backed" in body
    assert "data.quality_tier" in body
    assert "data.detail" in body


# ── all three are wired as Config sub-sections, not new top-level tabs ─────


def test_all_three_panels_are_wired_as_config_subsections():
    src = _read(DEBUG_JS)
    body = _extract_fn(src, "async function _renderConfig()")
    for host_id, fn in (
        ("applicant-config-captcha", "_renderCaptcha"),
        ("applicant-config-capacity", "_renderCapacity"),
        ("applicant-config-embedding", "_renderEmbedding"),
    ):
        assert host_id in body
        assert fn in body
    assert "wireRetry(sectionHost" in body
    tabs = re.search(r"const TABS = \[.*?\];\n", src, re.S)
    assert tabs
    for name in ("captcha", "capacity", "embedding"):
        assert name not in tabs.group(0)


# ── syntax smoke ─────────────────────────────────────────────────────────────


def test_node_check_applicant_debug_js(node_available):
    res = subprocess.run(
        ["node", "--check", str(DEBUG_JS)],
        capture_output=True,
        timeout=15,
        text=True,
    )
    assert res.returncode == 0, f"node --check failed:\n{res.stderr}"
