"""Front-door regression coverage for opt-in error telemetry (P5-3).

Mirrors the established precedent for this exact kind of Settings > System
panel (``test_applicant_health_panel_js.py``): wiring/composition facts are
asserted with plain regex over the real shipped source (index.html host div +
script tag, settings.js's System-tab mount, the engine client + workspace
proxy route), and the pure HTML-building functions in
``static/js/applicantTelemetrySettings.js`` are sliced out of the live file
and run for real under ``node --input-type=module`` against a tiny local
``esc()`` stand-in — same tradeoff that file's own header comment documents.

The privacy-critical guarantees (default OFF, hard-off in local-only mode,
the redaction chokepoint, the server-side gate) are pinned on the ENGINE side
in ``tests/unit/test_telemetry_reporting.py`` and the proxy behavior in
``test_applicant_telemetry_routes.py`` — this file only proves the toggle is
actually reachable from the Settings UI and renders the engine's own
``effective``/``local_only`` computation honestly, never re-deriving it.

Every assertion below was hand-verified to go RED against a temporary revert
of the corresponding source line, then GREEN again after restoring.
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
_TELEMETRY_JS = _JS_DIR / "applicantTelemetrySettings.js"
_SETTINGS_JS = _JS_DIR / "settings.js"
_INDEX_HTML = _REPO / "static" / "index.html"
_SETUP_ROUTES = _REPO / "routes" / "applicant_setup_routes.py"
_ENGINE_CLIENT = _REPO / "src" / "applicant_engine.py"
_HAS_NODE = shutil.which("node") is not None


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _run_node(script: str) -> dict:
    res = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=_REPO,
        capture_output=True,
        timeout=15,
        text=True,
    )
    if res.returncode != 0:
        raise AssertionError(f"node failed:\nSTDOUT:{res.stdout}\nSTDERR:{res.stderr}")
    return json.loads(res.stdout)


@pytest.fixture(scope="module")
def node_available():
    if not _HAS_NODE:
        pytest.skip("node binary not on PATH")


# ── Reachability: engine surface + workspace bridge ─────────────────────────


def test_engine_client_has_telemetry_methods():
    src = _read(_ENGINE_CLIENT)
    assert "async def setup_get_telemetry" in src
    assert '"/api/setup/telemetry"' in src
    assert "async def setup_configure_telemetry" in src


def test_proxy_route_gates_read_with_require_user_and_write_with_can_configure():
    src = _read(_SETUP_ROUTES)
    fn = re.search(r"async def get_telemetry\(request: Request\).*?\n\n    @router", src, re.S)
    assert fn, "expected a get_telemetry route handler"
    assert "require_user(request)" in fn.group(0)

    write_fn = re.search(r"async def set_telemetry\(.*?\n\n    # ── step 3: fonts", src, re.S)
    assert write_fn, "expected a set_telemetry route handler"
    assert "require_privilege(request, _CONFIG_PRIV)" in write_fn.group(0)


def test_proxy_forwards_only_the_fields_the_caller_actually_sent():
    """Pins the ``exclude_unset=True`` partial-update contract every sibling
    Settings write in this router uses (channels/automation) -- a field the
    caller didn't send must not be forwarded as an explicit null."""
    src = _read(_SETUP_ROUTES)
    write_fn = re.search(r"async def set_telemetry\(.*?\n\n    # ── step 3: fonts", src, re.S)
    assert write_fn
    assert "model_dump(exclude_unset=True)" in write_fn.group(0)


# ── Wiring: index.html host divs + eager script tag ─────────────────────────


def test_index_html_has_settings_system_telemetry_host():
    src = _read(_INDEX_HTML)
    assert 'id="ao-settings-telemetry"' in src


def test_index_html_telemetry_host_sits_after_health_and_before_data_backup():
    src = _read(_INDEX_HTML)
    system_idx = src.index('data-settings-panel="system"')
    health_idx = src.index('id="ao-settings-health"', system_idx)
    telemetry_idx = src.index('id="ao-settings-telemetry"', system_idx)
    backup_idx = src.index("Data Backup", system_idx)
    assert system_idx < health_idx < telemetry_idx < backup_idx


def test_index_html_loads_applicant_telemetry_settings_script():
    src = _read(_INDEX_HTML)
    assert 'src="/static/js/applicantTelemetrySettings.js"' in src


# ── Wiring: settings.js mounts the panel on the System tab ──────────────────


def test_settings_js_mounts_telemetry_settings_on_system_tab():
    src = _read(_SETTINGS_JS)
    fn = re.search(r"if \(tab === 'system'\) \{.*?\n  \}\n", src, re.S)
    assert fn, "expected the system-tab mount block in mountRelocatedSetupStep"
    body = fn.group(0)
    assert "window.mountApplicantTelemetrySettings" in body
    assert "ao-settings-telemetry" in body


# ── The module shape ────────────────────────────────────────────────────────


def test_module_exports_a_mount_function():
    src = _read(_TELEMETRY_JS)
    assert "export async function mountApplicantTelemetrySettings(host)" in src


def test_module_is_exposed_on_window_for_lazy_mounting():
    src = _read(_TELEMETRY_JS)
    assert "window.mountApplicantTelemetrySettings = mountApplicantTelemetrySettings" in src


def test_module_talks_only_to_the_owner_scoped_setup_proxy():
    src = _read(_TELEMETRY_JS)
    assert "const BASE = '/api/applicant/setup/telemetry';" in src
    assert "/api/setup/telemetry" not in src.replace("/api/applicant/setup/telemetry", "")


def test_module_reuses_the_shared_core_helpers_not_hand_rolled_fetch():
    """CLAUDE.md principle #1: lift-and-shift the established _fetchJSON/_post/
    _toast helpers (applicantCore.js), same as applicantAutomationSettings.js."""
    src = _read(_TELEMETRY_JS)
    assert "from './applicantCore.js'" in src
    assert "_fetchJSON" in src
    assert "_post" in src
    assert "_toast" in src


def test_module_has_no_hardcoded_collection_endpoint():
    """P5-3's DoD: no bundled/default vendor collector. The only ``https://``
    text in this file may be the placeholder's EXAMPLE domain (instructional
    copy the operator types over, never a live default) -- pin that the
    rendered ``value`` attribute is driven from ``status.endpoint`` alone
    (asserted elsewhere) and that no real third-party telemetry vendor is
    named/wired anywhere in this file (the same vendor list the
    landing-page privacy-wedge suite checks for)."""
    src = _read(_TELEMETRY_JS)
    https_occurrences = re.findall(r"https://\S+", src)
    assert https_occurrences, "expected the placeholder's example https:// domain"
    assert all("your-own-telemetry-endpoint.example.com" in occ for occ in https_occurrences), (
        f"unexpected hardcoded URL(s) in {_TELEMETRY_JS.name}: {https_occurrences}"
    )
    vendor_signatures = re.compile(
        r"sentry\.io|bugsnag|rollbar|honeybadger|datadoghq|google-analytics|"
        r"segment\.com|mixpanel|amplitude\.com",
        re.IGNORECASE,
    )
    assert not vendor_signatures.search(src), "no third-party telemetry vendor may be named/wired here"


def test_module_never_mentions_fr_or_nfr_jargon_in_user_facing_copy():
    """White-label rule: plain language only, no spec-jargon leaking into copy."""
    src = _read(_TELEMETRY_JS)
    assert not re.search(r"\bFR-[A-Z]+-\d+\b", src)
    assert not re.search(r"\bNFR-[A-Z]+-\d+\b", src)


# ── Real execution: the pure HTML-building functions ────────────────────────


_ESC_STUB = (
    "function esc(s) { return (s == null ? '' : String(s))"
    ".replace(/[&<>\"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c])); }"
)


def _slice_between(src: str, start_marker: str, end_marker: str) -> str:
    start = src.index(start_marker)
    end = src.index(end_marker, start)
    return src[start:end]


def _panel_fns_source() -> str:
    src = _read(_TELEMETRY_JS)
    return _slice_between(
        src, "function _bannerHTML(status) {", "function _readForm(host) {"
    )


def test_banner_is_empty_when_not_local_only(node_available):
    script = f"""
    {_ESC_STUB}
    {_panel_fns_source()}
    console.log(JSON.stringify({{ banner: _bannerHTML({{ local_only: false }}) }}));
    """
    out = _run_node(script)
    assert out["banner"] == ""


def test_banner_warns_when_local_only_is_on(node_available):
    script = f"""
    {_ESC_STUB}
    {_panel_fns_source()}
    console.log(JSON.stringify({{ banner: _bannerHTML({{ local_only: true }}) }}));
    """
    out = _run_node(script)
    assert "private mode" in out["banner"].lower()
    assert "off" in out["banner"].lower()


def test_card_defaults_to_unchecked_and_empty_endpoint(node_available):
    """Default-OFF, rendered: the checkbox is unchecked and the endpoint field
    is blank when the status payload has nothing saved yet."""
    script = f"""
    {_ESC_STUB}
    {_panel_fns_source()}
    const html = _cardHTML({{ enabled: false, endpoint: '', local_only: false, effective: false }});
    console.log(JSON.stringify({{ html }}));
    """
    out = _run_node(script)
    assert "checked" not in out["html"].split('id="ats-enabled"')[1].split(">")[0]
    assert 'value=""' in out["html"]
    assert "Currently off." in out["html"]


def test_card_reflects_enabled_and_endpoint_when_saved(node_available):
    script = f"""
    {_ESC_STUB}
    {_panel_fns_source()}
    const html = _cardHTML({{
      enabled: true, endpoint: 'https://telemetry.example.com/ingest',
      local_only: false, effective: true,
    }});
    console.log(JSON.stringify({{ html }}));
    """
    out = _run_node(script)
    assert 'id="ats-enabled" data-as-field="enabled" checked' in out["html"]
    assert "telemetry.example.com/ingest" in out["html"]
    assert "Currently active." in out["html"]


def test_card_shows_forced_off_by_private_mode_even_when_stored_enabled(node_available):
    """The honesty case: the operator opted in, but local-only mode wins --
    the card must say so plainly rather than claiming it's active."""
    script = f"""
    {_ESC_STUB}
    {_panel_fns_source()}
    const html = _cardHTML({{
      enabled: true, endpoint: 'https://telemetry.example.com/ingest',
      local_only: true, effective: false,
    }});
    console.log(JSON.stringify({{ html }}));
    """
    out = _run_node(script)
    assert "Currently off (private mode)." in out["html"]
    assert "no matter what is saved here" in out["html"]


def test_card_never_shows_a_hardcoded_placeholder_value():
    """The placeholder is instructional copy (an example), never a real,
    already-filled-in default endpoint -- ``value`` must stay driven by
    ``status.endpoint`` alone."""
    src = _read(_TELEMETRY_JS)
    fn = re.search(r"function _cardHTML\(status\) \{.*?\n\}\n", src, re.S)
    assert fn
    body = fn.group(0)
    assert 'value="${endpoint}"' in body
