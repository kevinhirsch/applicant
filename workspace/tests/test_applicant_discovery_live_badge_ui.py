"""Regression coverage for the live-vs-sample discovery source indicator
(dark-engine audit item 65).

With ``DISCOVERY_LIVE=false`` (the default -- see ``src/applicant/app/config.py``),
every discovery source is backed by an offline fake client that returns the exact
same registry shape as the real thing (``adapters/discovery/factory.py``), and the
``SampleSource`` emits synthetic ``example.test`` rows indistinguishable in the UI
from real discovery. This phase wires the full chain:

  * ``src/applicant/app/routers/discovery_sources.py`` -- adds a per-source
    ``live: bool`` to the ``GET /api/discovery-sources/{campaign_id}`` response,
    derived from ``DISCOVERY_LIVE`` (the ``sample`` key is always ``False``).
    Engine-level coverage lives in ``tests/unit/test_discovery_live_indicator.py``.
  * ``workspace/routes/applicant_campaigns_routes.py`` -- unchanged: the sources
    proxy already forwards ``items`` verbatim, so the new field passes through for
    free. Pinned in ``workspace/tests/test_applicant_discovery_live_badge.py``.
  * ``workspace/static/js/applicantCampaignSettings.js`` -- a per-source "Live" /
    "Sample data" badge, plus a plain-language banner when every source in a
    campaign is currently sample data. This file.

Follows the ``test_applicant_campaign_delete_ui.py`` convention: source-text regex
assertions for the browser-only renderer (no DOM-independent entry point cheap
enough to shim here). Each assertion was hand-verified to go RED when the
corresponding piece of the affordance is reverted, then GREEN again after
restoring (see the task's revert-verification pass).
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

_HAS_NODE = shutil.which("node") is not None


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def node_available():
    if not _HAS_NODE:
        pytest.skip("node binary not on PATH")


# ── per-source badge ─────────────────────────────────────────────────────────


def test_live_badge_helper_exists_and_covers_both_states():
    src = _read(CAMPAIGN_SETTINGS_JS)
    fn = re.search(r"function _liveBadge\(live\) \{.*?\n\}\n", src, re.S)
    assert fn, "expected a _liveBadge(live) renderer"
    body = fn.group(0)
    assert "Live" in body
    assert "Sample data" in body, "must use plain language, not DISCOVERY_LIVE jargon"


def test_live_badge_copy_has_no_upstream_jargon():
    """CLAUDE.md white-label rule: zero FR-/NFR- jargon and no raw env-var names
    (e.g. 'DISCOVERY_LIVE') in user-facing strings."""
    src = _read(CAMPAIGN_SETTINGS_JS)
    fn = re.search(r"function _liveBadge\(live\) \{.*?\n\}\n", src, re.S)
    assert fn
    body = fn.group(0)
    assert "DISCOVERY_LIVE" not in body
    assert not re.search(r"\bFR-|\bNFR-", body)


def test_render_sources_tags_each_row_with_the_live_badge():
    src = _read(CAMPAIGN_SETTINGS_JS)
    fn = re.search(r"function _renderSources\(host, campaignId, items\) \{.*?\n\}\n", src, re.S)
    assert fn, "expected a _renderSources(host, campaignId, items) renderer"
    body = fn.group(0)
    assert "_liveBadge(" in body
    assert "s.live" in body, "the badge must be driven by the engine's per-source live flag"


# ── campaign-wide sample-data banner ─────────────────────────────────────────


def test_campaign_card_reserves_a_sources_banner_slot():
    src = _read(CAMPAIGN_SETTINGS_JS)
    fn = re.search(r"function _campaignCard\(c\) \{.*?\n\}\n", src, re.S)
    assert fn, "expected a _campaignCard(c) renderer"
    body = fn.group(0)
    assert "cs-sources-banner" in body


def test_render_sources_fills_the_banner_when_nothing_is_live():
    src = _read(CAMPAIGN_SETTINGS_JS)
    fn = re.search(r"function _renderSources\(host, campaignId, items\) \{.*?\n\}\n", src, re.S)
    assert fn
    body = fn.group(0)
    assert "cs-sources-banner" in body
    assert "anyLive" in body
    # Plain language: names the concrete action (connect a real board), not jargon.
    assert "sample data" in body.lower()
    assert "connect a real job board" in body.lower()


def test_banner_copy_has_no_upstream_jargon():
    src = _read(CAMPAIGN_SETTINGS_JS)
    fn = re.search(r"function _renderSources\(host, campaignId, items\) \{.*?\n\}\n", src, re.S)
    assert fn
    body = fn.group(0)
    assert "DISCOVERY_LIVE" not in body
    assert not re.search(r"\bFR-|\bNFR-", body)


# ── syntax smoke ─────────────────────────────────────────────────────────────


def test_node_check_applicant_campaign_settings_js(node_available):
    res = subprocess.run(
        ["node", "--check", str(CAMPAIGN_SETTINGS_JS)],
        capture_output=True,
        timeout=15,
        text=True,
    )
    assert res.returncode == 0, f"node --check failed:\n{res.stderr}"
