"""Regression coverage for the campaign-delete "Danger zone" affordance
(dark-engine audit item 17): the engine's ``DELETE /api/campaigns/{id}``
(``src/applicant/app/routers/campaigns.py``, purging via
``DataLifecycleService``/``ErasureService``, #363/FR-CRIT-4/NFR-PRIV-1) had
no workspace proxy, no client method, and no UI -- users could create
campaigns forever and never remove one.

This phase wires the full chain:

  * ``workspace/src/applicant_engine.py`` -- new ``delete_campaign`` client
    method. Route-level behavior + the mandatory owner-isolation test live in
    ``workspace/tests/test_applicant_campaign_delete_routes.py``. This file
    only pins the SOURCE-level shape of the client method (not reimplemented).
  * ``workspace/routes/applicant_campaigns_routes.py`` -- new
    ``DELETE /api/applicant/campaigns/{campaign_id}`` proxy.
  * ``workspace/static/js/applicantCampaignSettings.js`` -- the new
    per-campaign "Danger zone -> Delete this campaign" affordance with a
    confirm step. This file.

Follows the ``test_applicant_round2_emailscan_ui.py`` convention for this
exact style of module: source-text regex assertions for the browser-only
renderer (no DOM-independent entry point cheap enough to shim here). Each
assertion below was hand-verified to go RED when the corresponding piece of
the affordance is reverted (stripping the danger-zone markup, dropping the
confirm gate, un-wiring the click handler, dropping the client method /
route), then confirmed GREEN again after restoring.
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


# ── the front-end affordance: per-campaign danger zone with a confirm gate ──


def test_campaign_card_renders_a_danger_zone_section():
    """Every campaign card must render an explicit "Danger zone" section --
    not a bare delete button dropped in among the routine controls."""
    src = _read(CAMPAIGN_SETTINGS_JS)
    fn = re.search(r"function _campaignCard\(c\) \{.*?\n\}\n", src, re.S)
    assert fn, "expected a _campaignCard(c) renderer"
    body = fn.group(0)
    assert "cs-danger-zone" in body
    assert "Danger zone" in body


def test_danger_zone_carries_a_delete_button_scoped_to_the_campaign():
    src = _read(CAMPAIGN_SETTINGS_JS)
    fn = re.search(r"function _campaignCard\(c\) \{.*?\n\}\n", src, re.S)
    assert fn
    body = fn.group(0)
    assert 'class="cal-btn cal-btn-danger cs-delete"' in body
    assert 'data-cs-id="${id}"' in body, "expected the delete button scoped to this campaign's id"


def test_danger_zone_copy_names_what_gets_purged_and_that_it_is_irreversible():
    """Plain-language warning, not jargon -- CLAUDE.md white-label rule.
    Must name concrete things the user cares about and say it cannot be undone."""
    src = _read(CAMPAIGN_SETTINGS_JS)
    fn = re.search(r"function _campaignCard\(c\) \{.*?\n\}\n", src, re.S)
    assert fn
    body = fn.group(0)
    assert "cannot be undone" in body
    assert "résumés" in body or "resumes" in body.lower()


def test_danger_zone_reuses_the_shared_danger_button_class_not_hand_rolled():
    """CLAUDE.md: reuse the workspace design system -- the same
    .cal-btn-danger class already used for calendar's per-item delete and
    applicantRemote's authorize button, not a bespoke red button."""
    src = _read(CAMPAIGN_SETTINGS_JS)
    assert "cal-btn-danger" in src


# ── the delete handler: confirms, then DELETEs through the owner-scoped proxy ──


def test_delete_handler_is_wired_on_the_delete_button():
    src = _read(CAMPAIGN_SETTINGS_JS)
    wire_fn = re.search(r"async function _wireCard\(host, card\) \{.*?\n\}\n", src, re.S)
    assert wire_fn, "expected an async _wireCard(host, card) function"
    body = wire_fn.group(0)
    assert "'.cs-delete'" in body or '".cs-delete"' in body
    assert "_del(" in body, "expected the handler to call the DELETE convenience wrapper"


def test_delete_handler_confirms_before_deleting():
    """A destructive, irreversible action must be gated behind an explicit
    confirm -- never fire on a single click."""
    src = _read(CAMPAIGN_SETTINGS_JS)
    wire_fn = re.search(r"async function _wireCard\(host, card\) \{.*?\n\}\n", src, re.S)
    assert wire_fn
    body = wire_fn.group(0)
    # The delete branch must call _confirm(...) and bail out when it resolves falsy.
    delete_branch = body[body.index("cs-delete") :]
    assert "_confirm(" in delete_branch
    assert "if (!ok) return;" in delete_branch


def test_confirm_helper_uses_the_shared_styled_confirm_not_a_native_confirm():
    """Same async confirm shape as applicantVault.js / applicantRemote.js:
    uiModule.styledConfirm with a window.confirm fallback -- not a bare
    native confirm() that bypasses the design system."""
    src = _read(CAMPAIGN_SETTINGS_JS)
    fn = re.search(r"async function _confirm\(message, opts\) \{.*?\n\}\n", src, re.S)
    assert fn, "expected an async _confirm(message, opts) helper"
    body = fn.group(0)
    assert "uiModule.styledConfirm" in body
    assert "window.confirm" in body  # fallback only


def test_confirm_dialog_is_marked_danger_and_names_the_campaign():
    src = _read(CAMPAIGN_SETTINGS_JS)
    wire_fn = re.search(r"async function _wireCard\(host, card\) \{.*?\n\}\n", src, re.S)
    assert wire_fn
    delete_branch = wire_fn.group(0)
    delete_branch = delete_branch[delete_branch.index("cs-delete") :]
    assert "danger: true" in delete_branch
    assert "cs-name-label" in delete_branch, "expected the confirm message to name the specific campaign"


def test_delete_handler_targets_the_owner_scoped_proxy_not_the_engine_directly():
    src = _read(CAMPAIGN_SETTINGS_JS)
    wire_fn = re.search(r"async function _wireCard\(host, card\) \{.*?\n\}\n", src, re.S)
    assert wire_fn
    delete_branch = wire_fn.group(0)
    delete_branch = delete_branch[delete_branch.index("cs-delete") :]
    assert "${BASE}/${encodeURIComponent(id)}" in delete_branch
    assert "/api/campaigns" not in delete_branch  # never the bare engine path


def test_delete_handler_re_renders_the_list_so_the_deleted_campaign_disappears():
    src = _read(CAMPAIGN_SETTINGS_JS)
    wire_fn = re.search(r"async function _wireCard\(host, card\) \{.*?\n\}\n", src, re.S)
    assert wire_fn
    delete_branch = wire_fn.group(0)
    delete_branch = delete_branch[delete_branch.index("cs-delete") :]
    assert "mountApplicantCampaignSettings(host)" in delete_branch


def test_del_convenience_wrapper_issues_a_delete_request():
    src = _read(CAMPAIGN_SETTINGS_JS)
    fn = re.search(r"function _del\(url\) \{.*?\n\}\n", src, re.S)
    assert fn, "expected a _del(url) DELETE convenience wrapper"
    assert "method: 'DELETE'" in fn.group(0)


# ── engine-client + proxy: the new method/route exist ───────────────────────


def test_engine_client_exposes_delete_campaign_method():
    """The workspace's ApplicantEngineClient carries the new delete_campaign
    method -- not an ad hoc inline request -- mirroring update_campaign."""
    src = _read(ENGINE_CLIENT_PY)
    assert "async def delete_campaign(self, campaign_id: str)" in src
    assert '"DELETE", f"/api/campaigns/{campaign_id}"' in src


def test_proxy_delete_route_reuses_the_owner_scoping_guard():
    """The new delete endpoint must validate the caller-supplied campaign_id
    against THIS request's own campaign fan-out BEFORE forwarding -- the
    exact same _owner_campaign_ids guard update_campaign uses, not a
    re-implemented (and possibly weaker) copy."""
    src = _read(CAMPAIGNS_ROUTES_PY)
    delete_fn = re.search(
        r'@router\.delete\("/\{campaign_id\}"\)\s*\n\s*async def delete_campaign\(.*?\n    return .*?\n',
        src,
        re.S,
    )
    assert delete_fn, "expected an async delete_campaign(...) route handler"
    body = delete_fn.group(0)
    assert "_owner_campaign_ids" in body
    assert "campaign_id not in owned" in body
    assert "engine.delete_campaign(" in body


def test_proxy_delete_route_is_registered_under_the_campaigns_prefix():
    src = _read(CAMPAIGNS_ROUTES_PY)
    assert '@router.delete("/{campaign_id}")' in src


# ── syntax smoke ─────────────────────────────────────────────────────────────


def test_node_check_applicant_campaign_settings_js(node_available):
    res = subprocess.run(
        ["node", "--check", str(CAMPAIGN_SETTINGS_JS)],
        capture_output=True,
        timeout=15,
        text=True,
    )
    assert res.returncode == 0, f"node --check failed:\n{res.stderr}"
