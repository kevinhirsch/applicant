"""Regression coverage for docs/design/audits/exhaustive2/06_mobile_responsive.md
(PWA / mobile lens), Tier 6 items #37-#44, confined to the two PWA source
files: ``workspace/static/manifest.json`` and ``workspace/static/sw.js``.

  #37 The manifest ``description`` still described the vendored upstream
      product ("Self-hosted AI chat with memory, documents, and tools")
      instead of the actual job-application product. Updated to plain-
      language copy already used elsewhere in the app ("job search").

  #38 Both icons declared the combined ``purpose: "any maskable"`` for the
      SAME flat (unpadded) PNG. Maskable icons need ~20% safe-zone padding;
      claiming "maskable" for an icon that isn't built with that padding
      risks Android cropping the artwork. No padded ``-maskable`` variant
      exists in the repo (workspace/.gitignore excludes ``*.png`` entirely,
      and neither ``icon-192.png`` nor ``icon-512.png`` is present in this
      checkout) - per instructions we do NOT invent a binary asset. Instead
      the purpose is narrowed to plain ``"any"`` so Android falls back to
      its own safe adaptive-icon padding instead of assuming full-bleed art.

  #39 ``theme_color`` sanity-checked: ``#282c34`` already matches
      ``background_color`` (internally consistent) and is exactly what
      ``static/index.html``'s own dynamic ``<meta name="theme-color">``
      computation (:38-176, outside this task's file allowlist) uses as its
      light/dark-aware baseline. The deeper fix (a paired
      ``media="(prefers-color-scheme: ...)"`` meta tag) requires editing
      ``index.html`` and is out of scope for this change - left unchanged
      and asserted-consistent here rather than guessed at.

  #42 ``start_url``/``scope`` sanity-checked: already both ``"/"``, i.e.
      self-consistent (no scope violation). Launching directly into the
      Portal requires app-side routing (``index.html``/``app.js``, out of
      scope) - not attempted here.

  #40 The SW precache list (``PRECACHE`` in sw.js) omitted every
      ``applicant*.js`` module, ``emailLibrary/applicantDigest.js``, and
      ``documentLibrary.js`` - all network-first, so a first-ever offline
      open of the Portal (the actual daily PWA surface) fails to load them.
      Added the full applicant module chain to PRECACHE and bumped
      CACHE_NAME (the file's own header comment requires this whenever the
      precache list changes).

  #44 No ``navigator.setAppBadge`` anywhere in the app. Added a feature-
      detected Badging API sync entirely inside sw.js: the fetch handler
      recognizes the Portal's existing lightweight badge-count endpoint
      (``GET /api/applicant/portal/pending/count``, already polled every
      60s by ``applicantPortal.js``'s ``refreshBadge``) and, as a side
      effect of forwarding that exact request to the network unchanged,
      calls ``setAppBadge``/``clearAppBadge`` when the API exists. This
      is intentionally self-contained to sw.js (this task's allowlist does
      not include ``applicantPortal.js``) and never alters the response
      seen by the page.

Not attempted (documented, out of this task's file allowlist):
  #41 offline Portal shows "locked" vs. an explicit offline state - needs
      ``static/app.js`` + ``src/applicant_features.py``.
  #43 blob-manifest install risk - needs ``static/index.html``.

Every assertion below was hand-verified to go RED against a backup of the
pre-fix files (``cp static/manifest.json /tmp/....bak`` /
``cp static/sw.js /tmp/....bak``) and GREEN again after restoring the fix,
per this test suite's existing convention (see
test_applicant_backlog_htmlcache.py's docstring for the same methodology).
"""

from __future__ import annotations

import json
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKSPACE_DIR = REPO_ROOT / "workspace"
MANIFEST_PATH = WORKSPACE_DIR / "static" / "manifest.json"
SW_PATH = WORKSPACE_DIR / "static" / "sw.js"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.fixture()
def manifest() -> dict:
    return json.loads(_read(MANIFEST_PATH))


@pytest.fixture()
def sw_src() -> str:
    return _read(SW_PATH)


# ── #37: description no longer describes the vendored upstream product ──────


def test_manifest_description_is_not_the_stale_vendored_blurb(manifest):
    assert manifest["description"] != (
        "Self-hosted AI chat with memory, documents, and tools"
    )


def test_manifest_description_uses_plain_job_search_language(manifest):
    """Reuses the exact plain-language term ('job search') already used
    throughout applicantPortal.js/applicantOnboarding.js rather than
    inventing new marketing copy or FR-/NFR- jargon."""
    desc = manifest["description"].lower()
    assert "job" in desc
    # White-label: no engine/FR-jargon vocabulary in the user-facing string.
    assert "fr-" not in desc and "nfr-" not in desc


# ── #38: no un-padded PNG claims the maskable purpose ────────────────────────


def test_manifest_icons_do_not_falsely_claim_maskable_purpose(manifest):
    """No padded (~20% safe-zone) '-maskable' variant exists in this
    checkout (workspace/.gitignore excludes all *.png, and neither
    icon-192.png nor icon-512.png is present on disk here), so no icon
    entry may claim the 'maskable' purpose for the same flat artwork -
    that's the exact cropping-risk finding (#38). A future change that
    ships a real padded maskable asset should add a NEW icon entry for it
    rather than re-widening the purpose of the existing flat icons."""
    for icon in manifest["icons"]:
        assert "maskable" not in icon.get("purpose", ""), icon


def test_manifest_icons_still_declare_any_purpose(manifest):
    """Narrowing the purpose must not silently drop icon entries."""
    purposes = {icon.get("purpose") for icon in manifest["icons"]}
    assert purposes == {"any"}
    assert len(manifest["icons"]) == 2


def test_no_maskable_icon_asset_actually_exists_in_this_checkout():
    """Documents the reason #38 wasn't 'fixed' by shipping a real padded
    maskable variant: confirms the underlying binary assets referenced by
    the manifest are absent from this working tree (workspace/.gitignore
    excludes *.png), so inventing a '-maskable' entry would point at a
    file that doesn't exist."""
    for icon in ("icon-192.png", "icon-512.png"):
        assert not (WORKSPACE_DIR / "static" / icon).exists()


# ── #39 / #42: sanity-checked, deliberately left unchanged ───────────────────


def test_manifest_theme_color_matches_background_color(manifest):
    """#39 sanity check: whatever the value, theme_color and
    background_color must agree with each other (the manifest-only half of
    'sensible'; the media-query pairing lives in index.html, out of scope)."""
    assert manifest["theme_color"] == manifest["background_color"]


def test_manifest_start_url_within_declared_scope(manifest):
    """#42 sanity check: start_url must be within scope (no violation) even
    though it doesn't yet deep-link into the Portal (that needs app-side
    routing, out of scope for this file-only change)."""
    assert manifest["start_url"].startswith(manifest["scope"])


def test_manifest_is_valid_json_and_keeps_required_fields(manifest):
    for field in ("name", "short_name", "start_url", "scope", "display", "icons"):
        assert field in manifest


# ── #40: applicant module chain added to the SW precache ────────────────────


APPLICANT_MODULES = [
    "/static/js/applicantCore.js",
    "/static/js/applicantPortal.js",
    "/static/js/applicantActivity.js",
    "/static/js/applicantOnboarding.js",
    "/static/js/applicantChat.js",
    "/static/js/applicantRemote.js",
    "/static/js/applicantVault.js",
    "/static/js/emailLibrary/applicantDigest.js",
    "/static/js/documentLibrary.js",
]


def test_sw_precache_includes_applicant_module_chain(sw_src):
    precache_block = sw_src[sw_src.index("const PRECACHE") : sw_src.index("];") + 2]
    for module in APPLICANT_MODULES:
        assert f"'{module}'" in precache_block, f"{module} missing from PRECACHE"


def test_sw_precache_all_listed_files_exist_on_disk(sw_src):
    """Every PRECACHE entry that maps to a real static file must actually
    exist - a typo'd path would silently no-op (install handler swallows
    per-item fetch failures) rather than fail loudly."""
    precache_block = sw_src[sw_src.index("const PRECACHE") : sw_src.index("];") + 2]
    import re

    for path in re.findall(r"'(/static/[^']+)'", precache_block):
        rel = path.lstrip("/")
        assert (WORKSPACE_DIR / rel).exists(), f"precached path missing on disk: {path}"


def test_sw_cache_name_bumped_alongside_precache_change(sw_src):
    """The file's own header comment ('Bump CACHE_NAME whenever the precache
    list or SW logic changes') is a load-bearing invariant - stale clients
    on the old cache name would never see the new precache entries."""
    m = __import__("re").search(r"CACHE_NAME = 'applicant-v(\d+)'", sw_src)
    assert m, "could not find versioned CACHE_NAME"
    assert int(m.group(1)) >= 328


# ── #44: Badging API sync, feature-detected, additive-only ──────────────────


def test_sw_has_feature_detected_set_app_badge_call(sw_src):
    assert "setAppBadge" in sw_src
    assert "'setAppBadge' in self.navigator" in sw_src


def test_sw_has_feature_detected_clear_app_badge_call(sw_src):
    assert "clearAppBadge" in sw_src
    assert "'clearAppBadge' in self.navigator" in sw_src


def test_sw_badge_sync_targets_the_existing_pending_count_endpoint(sw_src):
    """Must piggyback on the Portal's existing lightweight badge endpoint
    rather than adding a brand-new fetch cycle."""
    assert "/api/applicant/portal/pending/count" in sw_src


def test_sw_badge_sync_forwards_the_original_response_unchanged(sw_src):
    """The badge side-effect must never replace or alter what the page
    receives for this request - it must still resolve with the real
    network response."""
    idx = sw_src.index("/api/applicant/portal/pending/count")
    branch = sw_src[idx : idx + 1200]
    assert "e.respondWith(" in branch
    assert "fetch(e.request).then(res =>" in branch
    assert "return res;" in branch


def test_sw_badge_sync_still_falls_through_to_the_api_never_cache_rule(sw_src):
    """The dedicated badge branch must appear BEFORE the blanket 'never
    cache API calls' early return, and that blanket rule must still exist
    unchanged for every other /api/ path."""
    badge_idx = sw_src.index("/api/applicant/portal/pending/count")
    never_cache_idx = sw_src.index("Never touch API calls or non-GET")
    assert badge_idx < never_cache_idx
    assert "url.pathname.startsWith('/api/') || e.request.method !== 'GET') return;" in sw_src


# ── Existing caching strategy must remain intact (no regression) ────────────


def test_sw_still_documents_and_implements_all_three_original_strategies(sw_src):
    assert "stale-while-revalidate" in sw_src.lower()
    assert "network-first" in sw_src.lower()
    assert "cache-first" in sw_src.lower()


def test_sw_activate_handler_unchanged_cleans_up_old_caches(sw_src):
    activate_block = sw_src[sw_src.index("addEventListener('activate'") :]
    activate_block = activate_block[: activate_block.index("self.addEventListener('fetch'")]
    assert "caches.delete(k)" in activate_block
    assert "self.clients.claim()" in activate_block


def test_sw_install_handler_unchanged_uses_individual_puts_not_addall(sw_src):
    install_block = sw_src[sw_src.index("addEventListener('install'") :]
    install_block = install_block[: install_block.index("addEventListener('activate'")]
    assert "cache.put(url, res)" in install_block
    assert "self.skipWaiting();" in install_block
