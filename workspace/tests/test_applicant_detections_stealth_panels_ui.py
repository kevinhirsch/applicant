"""Regression coverage for the Debug modal's "Detection events" and "Stealth
posture" panels (dark-engine audit items #26 / #27).

Both engine endpoints (``GET /api/admin/detections/{campaign_id}`` and
``GET /api/admin/stealth``) already existed and were already proxied
(``workspace/routes/applicant_admin_routes.py`` -> ``/api/applicant/admin/
detections/{campaign_id}`` and ``/api/applicant/admin/stealth``, both backed by
``ApplicantEngineClient.admin_detections`` / ``admin_stealth`` in
``workspace/src/applicant_engine.py``) -- the gap was purely front-end: no JS
anywhere ever read either proxy. (The only prior consumer of the ``/stealth``
payload was the narrow ``/api/applicant/remote/caveat`` lane, which only ever
surfaces the single ``caveat``/``egress_caveat`` text line, never the fuller
``egress`` posture -- see ``workspace/routes/applicant_remote_routes.py``.)

This file pins the SOURCE-level shape of the two new
``workspace/static/js/applicantDebug.js`` sub-section renderers wired into the
Config pane (mirrors item #86 / the item #34 Diagnostics precedent). No
engine or proxy files were touched -- both endpoints already existed and are
covered elsewhere (``tests/unit`` for the engine route,
``workspace/tests/test_applicant_admin_routes.py`` for the proxy).

Follows the ``test_applicant_prefill_diagnostics_ui.py`` convention for this
class of browser-only module: source-text regex assertions (no DOM-independent
entry point cheap enough to shim here). Each assertion below was verified, by
hand, to go red when the corresponding piece of wiring is reverted (stripping
a renderer, un-wiring it from Config, restoring the pre-change file), then
confirmed green again after restoring -- see the revert-verification note at
the bottom of this docstring's authoring session; re-run manually with:

    cp workspace/static/js/applicantDebug.js /tmp/applicantDebug.js.bak
    git show HEAD~1:workspace/static/js/applicantDebug.js > workspace/static/js/applicantDebug.js
    uv run pytest -q workspace/tests/test_applicant_detections_stealth_panels_ui.py  # expect failures
    cp /tmp/applicantDebug.js.bak workspace/static/js/applicantDebug.js
    uv run pytest -q workspace/tests/test_applicant_detections_stealth_panels_ui.py  # expect green
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


# ── Detection events (dark-engine audit #26) ────────────────────────────────


def test_detections_renderer_exists_and_fetches_the_admin_proxy():
    src = _read(DEBUG_JS)
    body = _extract_fn(src, "async function _renderDetections(host)")
    assert "${ADMIN}/detections/" in body
    assert "_fetchJSON(" in body
    assert "_campaignId" in body


def test_detections_renderer_renders_real_entries_not_a_fabricated_list():
    """Must map over the engine's own `detections` array (data.detections) --
    never a hardcoded/sample list."""
    src = _read(DEBUG_JS)
    body = _extract_fn(src, "async function _renderDetections(host)")
    assert "data.detections" in body
    assert "entries.map(" in body
    assert "esc(" in body, "expected entries to be escaped, not raw-injected"
    assert "e.signal_type" in body
    assert "e.detail" in body


def test_detections_renderer_requires_a_campaign_and_soft_degrades_offline():
    src = _read(DEBUG_JS)
    body = _extract_fn(src, "async function _renderDetections(host)")
    assert "_needCampaignIn(host)" in body, "campaign-scoped, mirrors the Sources sub-section"
    assert "_renderOffline(" in body
    assert "_empty(" in body


def test_detections_labels_are_plain_language_not_raw_signal_codes():
    """White-label + plain-language: the rendered copy must not just dump the
    raw machine ``signal_type`` string (e.g. 'blocked_403') at the user."""
    src = _read(DEBUG_JS)
    assert "_detectionLabel(" in src
    labels = re.search(r"const _DETECTION_LABELS = \{.*?\n\};\n", src, re.S)
    assert labels, "expected a signal_type -> plain-language label table"
    labels_body = labels.group(0)
    fn_body = _extract_fn(src, "function _detectionLabel(signalType)")
    # A human sentence, not a bare code, for at least the common signal types.
    assert "CAPTCHA" in labels_body
    assert "blocked" in labels_body.lower() or "rate-limited" in labels_body.lower()
    # Falls back to an honest generic line for an unrecognized signal type --
    # never renders raw jargon like the engine's own snake_case constant.
    assert "automated browsing" in fn_body.lower()


def test_detections_renderer_avoids_upstream_jargon():
    src = _read(DEBUG_JS)
    body = _extract_fn(src, "async function _renderDetections(host)")
    assert not re.search(r"\bFR-[A-Z]+-\d+\b", body)
    assert not re.search(r"\bNFR-[A-Z]+-\d+\b", body)


# ── Stealth posture (dark-engine audit #27) ─────────────────────────────────


def test_stealth_renderer_exists_and_fetches_the_admin_proxy():
    src = _read(DEBUG_JS)
    body = _extract_fn(src, "async function _renderStealth(host)")
    assert "${ADMIN}/stealth" in body
    assert "_fetchJSON(" in body


def test_stealth_renderer_renders_real_egress_posture_not_fabricated():
    """Must read the engine's own `egress` object (mode / is_direct_residential
    / proxy_configured) and the honest caveat text -- never hardcoded values."""
    src = _read(DEBUG_JS)
    body = _extract_fn(src, "async function _renderStealth(host)")
    assert "data.egress" in body
    assert "egress.mode" in body
    assert "egress.is_direct_residential" in body
    assert "egress.proxy_configured" in body
    assert "data.caveat" in body or "data.egress_caveat" in body
    assert "esc(" in body


def test_stealth_renderer_is_engine_wide_not_campaign_scoped_and_soft_degrades():
    """Mirrors Tools/Diagnostics/Update: process-global, no campaign guard."""
    src = _read(DEBUG_JS)
    body = _extract_fn(src, "async function _renderStealth(host)")
    assert "_needCampaign" not in body
    assert "_renderOffline(" in body


def test_stealth_renderer_avoids_upstream_jargon():
    src = _read(DEBUG_JS)
    body = _extract_fn(src, "async function _renderStealth(host)")
    assert not re.search(r"\bFR-[A-Z]+-\d+\b", body)
    assert not re.search(r"\bNFR-[A-Z]+-\d+\b", body)


# ── wired into Config as sub-sections, not new top-level tabs ───────────────


def test_both_panels_are_wired_as_config_subsections():
    """Mirrors item #86: sub-sections of the Config pane, not separate
    top-level tabs, to keep the tab strip within its 5-7 ceiling."""
    src = _read(DEBUG_JS)
    body = _extract_fn(src, "async function _renderConfig()")
    assert "applicant-config-detections" in body
    assert "_renderDetections" in body
    assert "applicant-config-stealth" in body
    assert "_renderStealth" in body
    # Each sub-section gets its own host + retry wiring, like its siblings.
    assert "wireRetry(sectionHost" in body


def test_neither_panel_is_a_new_top_level_tab():
    src = _read(DEBUG_JS)
    tabs = re.search(r"const TABS = \[.*?\];\n", src, re.S)
    assert tabs
    assert "detections" not in tabs.group(0)
    assert "stealth" not in tabs.group(0)


# ── syntax smoke ─────────────────────────────────────────────────────────────


def test_node_check_applicant_debug_js(node_available):
    res = subprocess.run(
        ["node", "--check", str(DEBUG_JS)],
        capture_output=True,
        timeout=15,
        text=True,
    )
    assert res.returncode == 0, f"node --check failed:\n{res.stderr}"
