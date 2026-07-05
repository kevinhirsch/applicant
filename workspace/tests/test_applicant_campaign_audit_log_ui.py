"""Regression coverage for the campaign "Download activity log" affordance
(dark-engine audit item 31): the engine's ordered per-campaign audit-log
export (``src/applicant/app/routers/audit.py``, proxied at
``GET /api/admin/audit-log/{campaign_id}/export.json``) was reachable only
from an admin account (``workspace/routes/applicant_admin_routes.py``) even
though every action in it belongs to the single owner of this deployment.

This phase wires the owner-scoped chain:

  * ``workspace/routes/applicant_campaigns_routes.py`` -- new
    ``GET /api/applicant/campaigns/{campaign_id}/audit-log/export.json``
    proxy, owner-scoped with the SAME ``_owner_campaign_ids`` guard
    ``update_campaign``/``delete_campaign`` already use in this file. Route
    behavior + the mandatory owner-isolation test live in
    ``test_applicant_campaigns_routes.py``. This file only pins the
    SOURCE-level shape of the front-end affordance (no engine change and no
    new client method -- ``audit_log_campaign_export`` already existed on
    ``ApplicantEngineClient`` for the admin lane; the new route reuses it).
  * ``workspace/static/js/applicantCampaignSettings.js`` -- the new
    per-campaign "Download activity log" button, sitting with the routine
    save/archive/duplicate controls -- NOT inside the danger zone (a
    download is a normal, non-destructive action).

Follows the ``test_applicant_campaign_clone_ui.py`` convention for this exact
style of module: source-text regex assertions for the browser-only renderer
(no DOM-independent entry point cheap enough to shim here). Each assertion
below was hand-verified to go RED when the corresponding piece of the
affordance is reverted (dropping the button, un-wiring the click handler,
dropping the route), then confirmed GREEN again after restoring.
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKSPACE_DIR = REPO_ROOT / "workspace"
CAMPAIGN_SETTINGS_JS = WORKSPACE_DIR / "static" / "js" / "applicantCampaignSettings.js"
CAMPAIGNS_ROUTES_PY = WORKSPACE_DIR / "routes" / "applicant_campaigns_routes.py"

_HAS_NODE = shutil.which("node") is not None


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def node_available():
    if not _HAS_NODE:
        pytest.skip("node binary not on PATH")


# ── the front-end affordance: a Download activity log control ──────────────


def test_campaign_card_renders_a_download_activity_log_button():
    src = _read(CAMPAIGN_SETTINGS_JS)
    fn = re.search(r"function _campaignCard\(c\) \{.*?\n\}\n", src, re.S)
    assert fn, "expected a _campaignCard(c) renderer"
    body = fn.group(0)
    assert 'class="cal-btn cs-audit-log"' in body
    assert 'data-cs-id="${id}"' in body
    assert "Download activity log" in body


def test_download_button_sits_with_the_routine_controls_not_the_danger_zone():
    """CLAUDE.md task boundary: a download is a normal, non-destructive
    action -- it must live alongside save/archive/duplicate, not inside the
    irreversible-delete danger zone (mirrors the Duplicate button's own
    placement assertion)."""
    src = _read(CAMPAIGN_SETTINGS_JS)
    fn = re.search(r"function _campaignCard\(c\) \{.*?\n\}\n", src, re.S)
    assert fn
    body = fn.group(0)
    audit_idx = body.index("cs-audit-log")
    danger_idx = body.index("cs-danger-zone")
    delete_idx = body.index("cs-delete")
    assert audit_idx < danger_idx, "Download activity log must render before the danger zone"
    assert audit_idx < delete_idx


def test_download_button_reuses_the_shared_button_class_not_hand_rolled():
    """CLAUDE.md: reuse the workspace design system -- the plain .cal-btn
    class already used for Save changes / Archive / Duplicate, not a bespoke
    button."""
    src = _read(CAMPAIGN_SETTINGS_JS)
    fn = re.search(r"function _campaignCard\(c\) \{.*?\n\}\n", src, re.S)
    assert fn
    body = fn.group(0)
    assert re.search(r'class="cal-btn cs-audit-log"', body)


def test_download_button_click_handler_opens_the_owner_scoped_export_url():
    """The click handler must hit the NEW owner-scoped proxy path (not the
    admin-gated one), scoped to the correct campaign id."""
    src = _read(CAMPAIGN_SETTINGS_JS)
    fn = re.search(r"async function _wireCard\(host, card\) \{.*?\n\}\n", src, re.S)
    assert fn, "expected a _wireCard(host, card) wiring function"
    body = fn.group(0)
    assert "cs-audit-log" in body
    assert "/audit-log/export.json" in body
    # Uses the SAME owner-scoped BASE constant as every other call in this
    # module -- never a hardcoded /api/applicant/admin/... admin-gated path.
    assert "${BASE}/${encodeURIComponent(id)}/audit-log/export.json" in body


def test_engine_client_method_is_not_reimplemented():
    """CLAUDE.md principle #1 (lift-and-shift, never rebuild): the new
    campaigns-routes export must reuse the SAME ``audit_log_campaign_export``
    client method the admin lane already uses -- not a second implementation
    of the same download."""
    engine_src = _read(WORKSPACE_DIR / "src" / "applicant_engine.py")
    assert engine_src.count("async def audit_log_campaign_export(") == 1
    routes_src = _read(CAMPAIGNS_ROUTES_PY)
    assert "engine.audit_log_campaign_export(campaign_id)" in routes_src


@pytest.mark.usefixtures("node_available")
def test_campaign_settings_js_parses():
    result = subprocess.run(
        ["node", "--check", str(CAMPAIGN_SETTINGS_JS)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
