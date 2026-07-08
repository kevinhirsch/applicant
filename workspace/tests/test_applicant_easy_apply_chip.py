"""P1-11 — Easy Apply: detect & tag — front-door chip regression tests.

The engine detects Easy-Apply-style postings server-side at discovery time and
tags them (``JobPosting.easy_apply``); the tag rides the digest rows
(``easy_apply`` per role) and the tracker-board rows unchanged through the
thin proxies. These tests pin the two front-door surfaces that render it:

* the digest row (``emailLibrary/applicantDigest.js`` ``buildDigestRow``)
  shows an "Easy Apply" channel chip when ``row.easy_apply`` is truthy;
* the Tracker board (``applicantTracker.js`` ``_renderRow``) shows the same
  chip on rows whose application's posting carried the tag.

Both are render-only (detection only, per the story's zero-automation-risk
DoD): the chip is informational, gated on the server-computed flag, and never
adds a new action.
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess

import pytest

_WORKSPACE = pathlib.Path(__file__).resolve().parent.parent  # workspace/
_DIGEST_JS = _WORKSPACE / "static" / "js" / "emailLibrary" / "applicantDigest.js"
_TRACKER_JS = _WORKSPACE / "static" / "js" / "applicantTracker.js"

_HAS_NODE = shutil.which("node") is not None


def _digest_src() -> str:
    return _DIGEST_JS.read_text(encoding="utf-8")


def _tracker_src() -> str:
    return _TRACKER_JS.read_text(encoding="utf-8")


# ── digest row chip ──────────────────────────────────────────────────────────


def test_digest_row_renders_easy_apply_chip_gated_on_row_flag():
    src = _digest_src()
    # The chip only renders when the server-computed flag is truthy.
    assert re.search(r"if\s*\(\s*row\.easy_apply\s*\)", src), (
        "buildDigestRow must gate the Easy Apply chip on row.easy_apply"
    )
    assert "applicant-easy-apply-chip" in src
    assert "'Easy Apply'" in src


def test_digest_chip_has_a_plain_language_tooltip():
    src = _digest_src()
    assert "quick-apply flow" in src, (
        "the chip needs a plain-language tooltip explaining what the channel means"
    )


# ── tracker row chip ─────────────────────────────────────────────────────────


def test_tracker_row_renders_easy_apply_chip_gated_on_app_flag():
    src = _tracker_src()
    assert "_easyApplyChip" in src
    assert re.search(r"!app\.easy_apply\s*\)\s*return\s*''", src), (
        "_easyApplyChip must return an empty string for untagged rows"
    )
    assert "applicant-easy-apply-chip" in src
    # Composed into the row template alongside the signal badges.
    assert "${_easyApplyChip(app)}${_signalBadges(app)}" in src


def test_tracker_chip_is_informational_only():
    src = _tracker_src()
    chip_fn = src.split("function _easyApplyChip", 1)[1].split("function ", 1)[0]
    # Render-only: no click handler, no data-action hook on the chip itself.
    assert "addEventListener" not in chip_fn
    assert "data-tracker" not in chip_fn


# ── syntax (no bundler — node --check is the only front-end gate) ────────────


@pytest.mark.skipif(not _HAS_NODE, reason="node is not installed")
@pytest.mark.parametrize("path", [_DIGEST_JS, _TRACKER_JS])
def test_touched_js_parses(path):
    subprocess.run(["node", "--check", str(path)], check=True)
