"""Regression coverage for the campaign-clone "Duplicate" affordance
(dark-engine audit item 36): the engine's ``CampaignService.clone_campaign``
(``src/applicant/application/services/campaign_service.py``,
``POST /api/campaigns/{campaign_id}/clone`` in
``src/applicant/app/routers/campaigns.py``) had no workspace proxy, no client
method, and no UI -- the natural "same search, new city" move (duplicate a
campaign to try a variant of its criteria/settings) was unreachable.

This phase wires the full chain:

  * ``workspace/src/applicant_engine.py`` -- new ``clone_campaign`` client
    method. Route-level behavior + the mandatory owner-isolation test live in
    ``workspace/tests/test_applicant_campaign_clone_routes.py``. This file
    only pins the SOURCE-level shape of the client method (not reimplemented).
  * ``workspace/routes/applicant_campaigns_routes.py`` -- new
    ``POST /api/applicant/campaigns/{campaign_id}/clone`` proxy.
  * ``workspace/static/js/applicantCampaignSettings.js`` -- the new
    per-campaign "Duplicate" affordance, sitting with the routine
    save/archive controls -- NOT inside the danger zone (a duplicate is a
    normal, low-stakes action, unlike the irreversible delete). This file.

Follows the ``test_applicant_campaign_delete_ui.py`` convention for this exact
style of module: source-text regex assertions for the browser-only renderer
(no DOM-independent entry point cheap enough to shim here). Each assertion
below was hand-verified to go RED when the corresponding piece of the
affordance is reverted (dropping the duplicate button, un-wiring the click
handler, dropping the client method / route), then confirmed GREEN again
after restoring.
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
ENGINE_CLIENT_PY = WORKSPACE_DIR / "src" / "applicant_engine.py"

_HAS_NODE = shutil.which("node") is not None


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def node_available():
    if not _HAS_NODE:
        pytest.skip("node binary not on PATH")


# ── the front-end affordance: a Duplicate control, NOT in the danger zone ──


def test_campaign_card_renders_a_duplicate_button():
    src = _read(CAMPAIGN_SETTINGS_JS)
    fn = re.search(r"function _campaignCard\(c\) \{.*?\n\}\n", src, re.S)
    assert fn, "expected a _campaignCard(c) renderer"
    body = fn.group(0)
    assert 'class="cal-btn cs-duplicate"' in body
    assert 'data-cs-id="${id}"' in body


def test_duplicate_button_sits_with_the_routine_controls_not_the_danger_zone():
    """CLAUDE.md task boundary: Duplicate is a normal action -- it must live
    alongside save/archive, not inside the irreversible-delete danger zone."""
    src = _read(CAMPAIGN_SETTINGS_JS)
    fn = re.search(r"function _campaignCard\(c\) \{.*?\n\}\n", src, re.S)
    assert fn
    body = fn.group(0)
    duplicate_idx = body.index("cs-duplicate")
    danger_idx = body.index("cs-danger-zone")
    delete_idx = body.index("cs-delete")
    assert duplicate_idx < danger_idx, "Duplicate must render before the danger zone"
    assert duplicate_idx < delete_idx


def test_duplicate_button_reuses_the_shared_button_class_not_hand_rolled():
    """CLAUDE.md: reuse the workspace design system -- the plain .cal-btn
    class already used for Save changes / Archive, not a bespoke button."""
    src = _read(CAMPAIGN_SETTINGS_JS)
    fn = re.search(r"function _campaignCard\(c\) \{.*?\n\}\n", src, re.S)
    assert fn
    body = fn.group(0)
    assert 'class="cal-btn cs-save"' in body
    assert 'class="cal-btn cs-duplicate"' in body
    # Not styled as a danger button -- duplication is not destructive.
    assert 'cal-btn-danger cs-duplicate' not in body


# ── the duplicate handler: prompts for a name, then POSTs to the owner-scoped proxy ──


def test_duplicate_handler_is_wired_on_the_duplicate_button():
    src = _read(CAMPAIGN_SETTINGS_JS)
    wire_fn = re.search(r"async function _wireCard\(host, card\) \{.*?\n\}\n", src, re.S)
    assert wire_fn, "expected an async _wireCard(host, card) function"
    body = wire_fn.group(0)
    assert "'.cs-duplicate'" in body or '".cs-duplicate"' in body


def test_duplicate_handler_prompts_for_a_new_name():
    """A duplicate should let the owner name the copy -- not silently reuse
    the source campaign's name."""
    src = _read(CAMPAIGN_SETTINGS_JS)
    wire_fn = re.search(r"async function _wireCard\(host, card\) \{.*?\n\}\n", src, re.S)
    assert wire_fn
    body = wire_fn.group(0)
    duplicate_branch = body[body.index("cs-duplicate") :]
    assert "styledPrompt" in duplicate_branch
    assert "if (newName == null) return;" in duplicate_branch


def test_duplicate_handler_targets_the_owner_scoped_proxy_clone_endpoint():
    src = _read(CAMPAIGN_SETTINGS_JS)
    wire_fn = re.search(r"async function _wireCard\(host, card\) \{.*?\n\}\n", src, re.S)
    assert wire_fn
    body = wire_fn.group(0)
    duplicate_branch = body[body.index("cs-duplicate") : body.index("cs-delete")]
    assert "${BASE}/${encodeURIComponent(id)}/clone" in duplicate_branch
    assert "/api/campaigns" not in duplicate_branch  # never the bare engine path


def test_duplicate_handler_uses_the_post_convenience_wrapper():
    src = _read(CAMPAIGN_SETTINGS_JS)
    wire_fn = re.search(r"async function _wireCard\(host, card\) \{.*?\n\}\n", src, re.S)
    assert wire_fn
    body = wire_fn.group(0)
    duplicate_branch = body[body.index("cs-duplicate") : body.index("cs-delete")]
    assert "_post(" in duplicate_branch


def test_duplicate_handler_re_renders_the_list_so_the_new_campaign_appears():
    src = _read(CAMPAIGN_SETTINGS_JS)
    wire_fn = re.search(r"async function _wireCard\(host, card\) \{.*?\n\}\n", src, re.S)
    assert wire_fn
    body = wire_fn.group(0)
    duplicate_branch = body[body.index("cs-duplicate") : body.index("cs-delete")]
    assert "mountApplicantCampaignSettings(host)" in duplicate_branch


# ── engine-client + proxy: the new method/route exist ───────────────────────


def test_engine_client_exposes_clone_campaign_method():
    """The workspace's ApplicantEngineClient carries the new clone_campaign
    method -- not an ad hoc inline request -- mirroring delete_campaign."""
    src = _read(ENGINE_CLIENT_PY)
    assert "async def clone_campaign(self, campaign_id: str" in src
    assert '"POST", f"/api/campaigns/{campaign_id}/clone"' in src


def test_proxy_clone_route_reuses_the_owner_scoping_guard():
    """The new clone endpoint must validate the caller-supplied campaign_id
    against THIS request's own campaign fan-out BEFORE forwarding -- the
    exact same _owner_campaign_ids guard update_campaign/delete_campaign use,
    not a re-implemented (and possibly weaker) copy."""
    src = _read(CAMPAIGNS_ROUTES_PY)
    clone_fn = re.search(
        r'@router\.post\("/\{campaign_id\}/clone", status_code=201\)\s*\n\s*async def clone_campaign\(.*?\n        return .*?\n',
        src,
        re.S,
    )
    assert clone_fn, "expected an async clone_campaign(...) route handler"
    body = clone_fn.group(0)
    assert "_owner_campaign_ids" in body
    assert "campaign_id not in owned" in body
    assert "engine.clone_campaign(" in body


def test_proxy_clone_route_is_registered_under_the_campaigns_prefix():
    src = _read(CAMPAIGNS_ROUTES_PY)
    assert '@router.post("/{campaign_id}/clone", status_code=201)' in src


# ── syntax smoke ─────────────────────────────────────────────────────────────


def test_node_check_applicant_campaign_settings_js(node_available):
    res = subprocess.run(
        ["node", "--check", str(CAMPAIGN_SETTINGS_JS)],
        capture_output=True,
        timeout=15,
        text=True,
    )
    assert res.returncode == 0, f"node --check failed:\n{res.stderr}"
