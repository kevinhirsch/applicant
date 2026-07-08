"""Front-door regression coverage for the honest health panel (P1-3, #655).

Two testing strategies, mirroring the established precedent in
``test_applicant_backlog_dailyritual.py`` / ``test_applicant_backlog_todaymode.py``:

  1. Wiring/composition facts (index.html host divs + script tag,
     settings.js's System-tab mount, applicantPortal.js's import + host div +
     load calls, the workspace proxy's owner gate) are asserted with plain
     regex over the REAL shipped source text.
  2. The pure HTML-building logic in ``static/js/applicantHealth.js`` — the
     part actually worth exercising (fix-copy-only-when-degraded, the
     ``(required)`` tag, the degraded-names rollup, the banner shell) — is
     sliced out of the live file and run for REAL under ``node
     --input-type=module`` against a tiny local ``esc()`` stand-in (the
     module's own ``esc`` comes from ``applicantCore.js`` -> ``ui.js``, which
     pulls in enough browser-only surface that re-importing the whole chain
     headlessly isn't worth it for pure string-building functions — the same
     tradeoff ``test_applicant_backlog_dailyritual.py``'s header comment
     documents for this codebase's JS test harness).

Every assertion below was verified failing against a temporary revert of the
corresponding source line(s) before being left in its final, passing form.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent  # workspace/
_JS_DIR = _REPO / "static" / "js"
_HEALTH_JS = _JS_DIR / "applicantHealth.js"
_PORTAL_JS = _JS_DIR / "applicantPortal.js"
_SETTINGS_JS = _JS_DIR / "settings.js"
_INDEX_HTML = _REPO / "static" / "index.html"
_HEALTH_ROUTES = _REPO / "routes" / "applicant_health_routes.py"
_APP_PY = _REPO / "app.py"
_HAS_NODE = shutil.which("node") is not None


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _slice_between(src: str, start_marker: str, end_marker: str) -> str:
    start = src.index(start_marker)
    end = src.index(end_marker, start)
    return src[start:end]


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
    return json.loads(res.stdout)


@pytest.fixture(scope="module")
def node_available():
    if not _HAS_NODE:
        pytest.skip("node binary not on PATH")


# ── Reachability: engine surface + workspace bridge ─────────────────────────


def test_engine_client_has_health_capabilities_method():
    src = _read(_REPO / "src" / "applicant_engine.py")
    assert "async def health_capabilities" in src
    assert '"/api/health/capabilities"' in src


def test_proxy_route_is_owner_gated_not_merely_user_gated():
    src = _read(_HEALTH_ROUTES)
    assert "require_engine_owner" in src
    # Must not fall back to the weaker require_user-only gate for this read.
    assert "from src.auth_helpers import require_engine_owner" in src


def test_proxy_route_prefix_and_soft_degrade():
    src = _read(_HEALTH_ROUTES)
    assert '"/api/applicant/health"' in src
    assert "soft_degrade" in src


def test_app_registers_the_health_routes():
    src = _read(_APP_PY)
    assert "setup_applicant_health_routes" in src
    assert "routes.applicant_health_routes" in src


# ── Wiring: index.html host divs + eager script tag ─────────────────────────


def test_index_html_has_settings_system_health_host():
    src = _read(_INDEX_HTML)
    assert 'id="ao-settings-health"' in src


def test_index_html_health_host_sits_before_data_backup():
    src = _read(_INDEX_HTML)
    system_idx = src.index('data-settings-panel="system"')
    health_idx = src.index('id="ao-settings-health"', system_idx)
    backup_idx = src.index("Data Backup", system_idx)
    assert system_idx < health_idx < backup_idx


def test_index_html_loads_applicant_health_script():
    src = _read(_INDEX_HTML)
    assert 'src="/static/js/applicantHealth.js"' in src


# ── Wiring: settings.js mounts the panel on the System tab ──────────────────


def test_settings_js_mounts_health_panel_on_system_tab():
    src = _read(_SETTINGS_JS)
    assert "tab === 'system'" in src
    assert "window.mountApplicantHealthPanel" in src
    assert "ao-settings-health" in src


# ── Wiring: applicantPortal.js imports + hosts + calls the banner loader ────


def test_portal_imports_the_banner_renderer():
    src = _read(_PORTAL_JS)
    assert "renderApplicantPortalHealthBanner" in src
    assert "from './applicantHealth.js'" in src


def test_portal_has_a_dedicated_health_host_before_the_today_glance():
    src = _read(_PORTAL_JS)
    greeting_idx = src.index('id="applicant-portal-greeting"')
    health_idx = src.index('id="applicant-portal-health"', greeting_idx)
    today_idx = src.index('id="applicant-portal-today"', greeting_idx)
    assert greeting_idx < health_idx < today_idx


def test_portal_loads_health_on_open_and_on_manual_refresh():
    src = _read(_PORTAL_JS)
    # Fired from the boot-time open path (openApplicantPortal).
    open_body = _slice_between(src, "export async function openApplicantPortal", "\n}\n")
    assert "_loadHealth()" in open_body
    # Fired from the manual refresh button too, not just on first open.
    refresh_line = next(
        line for line in src.splitlines() if "applicant-portal-refresh" in line and "addEventListener" in line
    )
    assert "_loadHealth()" in refresh_line


# ── Real execution: the pure HTML-building functions ────────────────────────


_ESC_STUB = (
    "function esc(s) { return (s == null ? '' : String(s))"
    ".replace(/[&<>\"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c])); }"
)


def _panel_fns_source() -> str:
    src = _read(_HEALTH_JS)
    return _slice_between(
        src,
        "function _statusPillHTML(status) {",
        "async function _renderPanelInto(body) {",
    )


def _banner_fns_source() -> str:
    src = _read(_HEALTH_JS)
    return _slice_between(
        src,
        "function _bannerShellHTML(title, sub, tone) {",
        "export async function renderApplicantPortalHealthBanner(host) {",
    )


def test_status_pill_reads_real_vs_stub(node_available):
    script = f"""
    {_ESC_STUB}
    {_panel_fns_source()}
    const real = _statusPillHTML('real');
    const stub = _statusPillHTML('stub');
    console.log(JSON.stringify({{ real, stub }}));
    """
    out = _run_node(script)
    assert "Working" in out["real"]
    assert "Degraded" in out["stub"]


def test_capability_row_shows_fix_copy_only_when_degraded(node_available):
    script = f"""
    {_ESC_STUB}
    {_panel_fns_source()}
    const okCap = {{ name: 'orchestrator', label: 'Durable orchestrator', status: 'real', detail: 'shim', load_bearing: false, fix: '' }};
    const badCap = {{ name: 'postgres', label: 'Database (Postgres)', status: 'stub', detail: 'not reachable', load_bearing: true, fix: 'Set DATABASE_URL...' }};
    console.log(JSON.stringify({{
      ok: _capabilityRowHTML(okCap),
      bad: _capabilityRowHTML(badCap),
    }}));
    """
    out = _run_node(script)
    assert "Set DATABASE_URL" not in out["ok"]
    assert "(required)" not in out["ok"]  # not load-bearing
    assert "Set DATABASE_URL" in out["bad"]
    assert "(required)" in out["bad"]
    assert "Database (Postgres)" in out["bad"]


def test_capability_row_never_shows_fix_when_real_even_if_fix_text_present(node_available):
    # Defensive: a real capability must never render fix copy even if the
    # (malformed/stale) payload happened to carry one — the row's own
    # "degraded &&" guard, not just the API's own "fix only when stub" one.
    script = f"""
    {_ESC_STUB}
    {_panel_fns_source()}
    const cap = {{ name: 'browser', label: 'Automation browser', status: 'real', detail: 'ok', load_bearing: true, fix: 'should not render' }};
    console.log(JSON.stringify({{ row: _capabilityRowHTML(cap) }}));
    """
    out = _run_node(script)
    assert "should not render" not in out["row"]


def test_panel_summary_all_real_vs_degraded_count(node_available):
    script = f"""
    {_ESC_STUB}
    {_panel_fns_source()}
    const caps = [
      {{ name: 'a', status: 'real' }},
      {{ name: 'b', status: 'stub' }},
      {{ name: 'c', status: 'real' }},
    ];
    const allReal = _panelSummaryHTML({{ all_real: true, degraded: [] }}, caps);
    const oneDown = _panelSummaryHTML({{ all_real: false, degraded: ['b'] }}, caps);
    console.log(JSON.stringify({{ allReal, oneDown }}));
    """
    out = _run_node(script)
    assert "running for real" in out["allReal"]
    assert "1 of 3" in out["oneDown"]


def test_panel_body_html_composes_summary_and_every_row(node_available):
    script = f"""
    {_ESC_STUB}
    {_panel_fns_source()}
    const data = {{
      all_real: false,
      degraded: ['postgres'],
      capabilities: [
        {{ name: 'postgres', label: 'Database (Postgres)', status: 'stub', detail: 'down', load_bearing: true, fix: 'fix it' }},
        {{ name: 'orchestrator', label: 'Durable orchestrator', status: 'real', detail: 'shim', load_bearing: false, fix: '' }},
      ],
    }};
    console.log(JSON.stringify({{ body: _panelBodyHTML(data) }}));
    """
    out = _run_node(script)
    assert "Database (Postgres)" in out["body"]
    assert "Durable orchestrator" in out["body"]
    assert "fix it" in out["body"]


def test_degraded_names_maps_to_labels_and_falls_back_to_raw_name(node_available):
    script = f"""
    {_ESC_STUB}
    {_banner_fns_source()}
    const caps = [
      {{ name: 'postgres', label: 'Database (Postgres)' }},
      {{ name: 'browser', label: 'Automation browser' }},
    ];
    const named = _degradedNames(caps, ['postgres', 'browser']);
    const unknown = _degradedNames(caps, ['mystery_capability']);
    console.log(JSON.stringify({{ named, unknown }}));
    """
    out = _run_node(script)
    assert out["named"] == ["Database (Postgres)", "Automation browser"]
    assert out["unknown"] == ["mystery_capability"]


def test_banner_shell_escapes_and_composes_title_and_sub(node_available):
    script = f"""
    {_ESC_STUB}
    {_banner_fns_source()}
    console.log(JSON.stringify({{ html: _bannerShellHTML('Title <x>', 'Sub & more', 'danger') }}));
    """
    out = _run_node(script)
    assert "Title &lt;x&gt;" in out["html"]
    assert "Sub &amp; more" in out["html"]
    assert 'data-role="open-system"' in out["html"]


# ── Honesty: the client reads load_bearing off the payload, never re-derives it


def test_client_reads_load_bearing_from_the_server_payload():
    """``load_bearing`` is a SERVER truth (``capability_report.LOAD_BEARING``);
    the client only ever reads ``cap.load_bearing`` / ``data.load_bearing_degraded``
    off the payload — it must never hardcode its own list of which capability
    names "count", or a future engine-side change to what's load-bearing would
    silently stop matching the client's stale copy."""
    src = _read(_HEALTH_JS)
    assert "cap.load_bearing" in src or "cap && cap.load_bearing" in src
    assert "data.load_bearing_degraded" in src or "data && data.load_bearing_degraded" in src
