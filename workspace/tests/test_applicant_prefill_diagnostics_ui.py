"""Regression coverage for the pre-fill diagnostics ring UI (dark-engine audit
item #34).

``PrefillService.diagnostics()`` (engine) is a bounded, deduped ring of
plain-language operator messages for credential/LLM/login failures that
degrade gracefully -- built "so it is surfaced rather than lost" (its own
docstring) but had zero callers anywhere. This wires the full chain:

  * ``src/applicant/app/routers/admin.py`` -- new
    ``GET /api/admin/prefill-diagnostics`` route reading
    ``container.prefill_service.diagnostics()`` (engine-side; covered by
    ``tests/unit/test_prefill_diagnostics_route.py``, not this file).
  * ``workspace/src/applicant_engine.py`` -- new ``admin_prefill_diagnostics``
    client method.
  * ``workspace/routes/applicant_admin_routes.py`` -- new admin-gated proxy;
    route-level behavior (admin gating, soft-degrade, exact engine path) lives
    in ``workspace/tests/test_applicant_prefill_diagnostics.py``. This file
    only pins the SOURCE-level shape of the route.
  * ``workspace/static/js/applicantDebug.js`` -- the new "Diagnostics"
    sub-section of the Debug modal's Config pane. This file.

Follows the ``test_applicant_round2_emailscan_ui.py`` convention for this
class of browser-only module: source-text regex assertions (no DOM-independent
entry point cheap enough to shim here). Each assertion below was verified, by
hand, to go red when the corresponding piece of the wiring is reverted
(stripping the renderer, un-wiring it from Config, dropping the client method
or proxy route), then confirmed green again after restoring.
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
ADMIN_ROUTES_PY = WORKSPACE_DIR / "routes" / "applicant_admin_routes.py"
ENGINE_CLIENT_PY = WORKSPACE_DIR / "src" / "applicant_engine.py"

_HAS_NODE = shutil.which("node") is not None


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def node_available():
    if not _HAS_NODE:
        pytest.skip("node binary not on PATH")


# ── the front-end renderer: real ring contents, no fabrication ──────────────


def test_diagnostics_renderer_exists_and_fetches_the_admin_proxy():
    src = _read(DEBUG_JS)
    fn = re.search(r"async function _renderDiagnostics\(host\) \{.*?\n\}\n", src, re.S)
    assert fn, "expected an async _renderDiagnostics(host) renderer"
    body = fn.group(0)
    assert "${ADMIN}/prefill-diagnostics" in body
    assert "_fetchJSON(" in body


def test_diagnostics_renderer_renders_real_entries_not_a_fabricated_list():
    """Must map over the engine's own `diagnostics` array (data.diagnostics)
    -- never a hardcoded/sample message list."""
    src = _read(DEBUG_JS)
    fn = re.search(r"async function _renderDiagnostics\(host\) \{.*?\n\}\n", src, re.S)
    assert fn
    body = fn.group(0)
    assert "data.diagnostics" in body
    assert "entries.map(" in body
    assert "esc(" in body, "expected entries to be escaped, not raw-injected"


def test_diagnostics_renderer_handles_empty_ring_and_offline_states():
    src = _read(DEBUG_JS)
    fn = re.search(r"async function _renderDiagnostics\(host\) \{.*?\n\}\n", src, re.S)
    assert fn
    body = fn.group(0)
    assert "_renderOffline(" in body, "expected the offline soft-degrade branch"
    assert "_empty(" in body, "expected an empty-ring plain-language message"


def test_diagnostics_renderer_avoids_upstream_jargon():
    """White-label + plain-language: no FR-/NFR- requirement IDs or the raw
    engine method name leak into the rendered copy."""
    src = _read(DEBUG_JS)
    fn = re.search(r"async function _renderDiagnostics\(host\) \{.*?\n\}\n", src, re.S)
    assert fn
    body = fn.group(0)
    assert not re.search(r"\bFR-[A-Z]+-\d+\b", body)
    assert not re.search(r"\bNFR-[A-Z]+-\d+\b", body)


# ── wired into Config as a sub-section, not a 7th top-level tab ─────────────


def test_diagnostics_is_wired_as_a_config_subsection():
    """Mirrors item #86: Sources/Tools/Update are sub-sections of the Config
    pane, not separate top-level tabs, to keep the tab strip within its 5-7
    ceiling. Diagnostics must join them the same way."""
    src = _read(DEBUG_JS)
    fn = re.search(r"async function _renderConfig\(\) \{.*?\n\}\n", src, re.S)
    assert fn, "expected a _renderConfig() function"
    body = fn.group(0)
    assert "applicant-config-diagnostics" in body
    assert "_renderDiagnostics" in body


def test_diagnostics_is_not_a_new_top_level_tab():
    """The TABS array (the top-level tab strip) must stay unchanged -- no
    'diagnostics' entry there."""
    src = _read(DEBUG_JS)
    tabs = re.search(r"const TABS = \[.*?\];\n", src, re.S)
    assert tabs
    assert "diagnostics" not in tabs.group(0)


# ── engine-client + proxy: the new method/route exist ───────────────────────


def test_engine_client_exposes_admin_prefill_diagnostics():
    src = _read(ENGINE_CLIENT_PY)
    assert "async def admin_prefill_diagnostics(self)" in src
    assert '"/api/admin/prefill-diagnostics"' in src


def test_proxy_prefill_diagnostics_route_requires_admin_and_soft_degrades():
    src = _read(ADMIN_ROUTES_PY)
    start = src.index('@router.get("/prefill-diagnostics")')
    end = src.index("@router.get(\"/log/{application_id}\")", start)
    body = src[start:end]
    assert "async def prefill_diagnostics(request: Request) -> dict:" in body
    assert "_require_admin(request)" in body
    assert "_soft_get(" in body
    assert "engine.admin_prefill_diagnostics(" in body


def test_proxy_prefill_diagnostics_route_is_registered_under_the_admin_prefix():
    src = _read(ADMIN_ROUTES_PY)
    assert '@router.get("/prefill-diagnostics")' in src


# ── syntax smoke ─────────────────────────────────────────────────────────────


def test_node_check_applicant_debug_js(node_available):
    res = subprocess.run(
        ["node", "--check", str(DEBUG_JS)],
        capture_output=True,
        timeout=15,
        text=True,
    )
    assert res.returncode == 0, f"node --check failed:\n{res.stderr}"
