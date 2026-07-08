"""Hermetic tests for the service-worker release cache-bust (P0-6, DoD 5).

``src/sw_version.py`` stamps a content fingerprint of the shipped static
assets into the service worker's ``CACHE_NAME`` when ``/static/sw.js`` is
served, so a release (any changed .js/.css/.html) byte-changes the worker and
the browser's SW update cycle drops the previous release's caches. These
tests pin the stamping contract without booting the full app:

* the fingerprint is stable for identical trees and changes when any covered
  asset's bytes change (and when a file is renamed byte-identically);
* the rewrite stamps exactly the ``CACHE_NAME`` constant and leaves a worker
  without one untouched (never break the SW over the stamp);
* the REAL shipped ``static/sw.js`` is stampable (the constant exists in the
  form the rewrite matches) — the wiring in ``app.py`` composes this exact
  seam, which the source-composition assertion below pins.
"""

from __future__ import annotations

import pathlib
import re

from src.sw_version import stamp_sw_cache_name, static_asset_fingerprint

WORKSPACE = pathlib.Path(__file__).resolve().parent.parent


def _fp(static_dir: pathlib.Path) -> str:
    return static_asset_fingerprint(str(static_dir))


def test_fingerprint_changes_when_an_asset_changes(tmp_path):
    a = tmp_path / "a"
    a.mkdir()
    (a / "app.js").write_text("console.log(1)\n")
    (a / "style.css").write_text("body{}\n")
    before = _fp(a)
    assert re.fullmatch(r"[0-9a-f]{12}", before)

    b = tmp_path / "b"
    b.mkdir()
    (b / "app.js").write_text("console.log(2)\n")  # changed bytes
    (b / "style.css").write_text("body{}\n")
    assert _fp(b) != before


def test_fingerprint_is_stable_and_covers_renames(tmp_path):
    a = tmp_path / "a"
    a.mkdir()
    (a / "app.js").write_text("x\n")
    twin = tmp_path / "twin"
    twin.mkdir()
    (twin / "app.js").write_text("x\n")
    # Same relative tree, same bytes -> same fingerprint.
    assert _fp(a) == _fp(twin)

    renamed = tmp_path / "renamed"
    renamed.mkdir()
    (renamed / "app2.js").write_text("x\n")  # identical bytes, new name
    assert _fp(renamed) != _fp(a)


def test_fingerprint_ignores_non_shipped_files(tmp_path):
    a = tmp_path / "a"
    a.mkdir()
    (a / "app.js").write_text("x\n")
    before = _fp(a)
    b = tmp_path / "b"
    b.mkdir()
    (b / "app.js").write_text("x\n")
    (b / "notes.png").write_bytes(b"\x89PNG")  # not a code asset
    assert _fp(b) == before


def test_stamp_rewrites_cache_name_once_and_only_cache_name():
    src = "const CACHE_NAME = 'applicant-v328';\nconst OTHER = 'applicant-v328';\n"
    out = stamp_sw_cache_name(src, "abc123def456")
    assert "const CACHE_NAME = 'applicant-v328-abc123def456';" in out
    # Only the CACHE_NAME constant is stamped.
    assert "const OTHER = 'applicant-v328';" in out


def test_stamp_leaves_source_without_cache_name_untouched():
    src = "self.addEventListener('fetch', () => {});\n"
    assert stamp_sw_cache_name(src, "abc123def456") == src


def test_shipped_sw_source_is_stampable():
    source = (WORKSPACE / "static" / "sw.js").read_text(encoding="utf-8")
    stamped = stamp_sw_cache_name(source, "feedfacecafe")
    assert stamped != source
    assert re.search(r"const CACHE_NAME = 'applicant-v\d+-feedfacecafe';", stamped)


def test_app_serves_sw_through_the_stamp_seam():
    """Source-composition pin (same pattern as the other front-door tests):
    app.py must register /static/sw.js BEFORE the /static mount and route it
    through stamp_sw_cache_name(static_asset_fingerprint(...)) with no-cache,
    so the browser's SW update check always sees the release fingerprint."""
    source = (WORKSPACE / "app.py").read_text(encoding="utf-8")
    route_at = source.index('@app.get("/static/sw.js")')
    mount_at = source.index('app.mount("/static"')
    assert route_at < mount_at, "sw.js route must precede the /static mount to win routing"
    body = source[route_at:route_at + 1600]
    assert "stamp_sw_cache_name(source, static_asset_fingerprint(static_dir))" in body
    assert '"Cache-Control": "no-cache"' in body
