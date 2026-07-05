"""Regression coverage for the copy & voice audit
(``docs/design/audits/exhaustive2/02_copy_voice.md``), confined to this pass's
file lane: ``applicantDebug.js`` (the Activity/Debug admin surface).

Copy-only pass: no logic or DOM structure changed, only user-facing strings
(button/label tooltip text, banner text, and toast copy). This file follows
the established convention (``test_applicant_copy_voice_02_documents_digest.py``,
``test_applicant_exhaustive2_gallery_campaignsettings_a11y.py``): every fact is
read from the actual static file content via ``pathlib`` + regex — no browser,
no DOM, no real socket. Each assertion was verified, by hand, to go red when
the underlying fix is reverted (temporarily restore the pre-fix source from a
file-copy backup, rerun, see a real ``AssertionError``, then restore from the
backup — never ``git stash``) before this file was landed.

What this batch fixes (see the audit's "Live takeover, chat, vault, compare,
gallery, debug, nav chrome" section, findings 207/220-222/224/233/234/236/238):

* Finding #236 — "assistant"/"agent" mixed within one tooltip: the "Ask the
  assistant" overflow item's title now names the surface consistently ("Job
  Assistant") instead of switching to "the agent" mid-sentence.
* Finding #221 — the audit-log download error toast no longer surfaces the
  raw ``e.message`` (which can carry an HTTP status / raw server text via the
  ``Unexpected response (${status})`` fallback); it always shows the same
  calm, plain-language line.
* Finding #234 — British "favour" -> "favor" (the only ``-our`` spelling in
  the product) in the Insights conversion-so-far note.
* Finding #238 — "awaiting review" -> "in review" in the Variants approval-
  state label, matching the "in review" wording used elsewhere.
* Finding #222 — "digest" jargon in the Run-now explainer replaced with the
  panel's own name, "Daily updates".
* Finding #224 — "clamped" engineering verb replaced with plain "lowered to
  the cap" in the Run-controls daily-target note.
* Finding #220 — the machine-readable ``res.reason`` enum value can no longer
  reach a toast raw; only the mapped label or the generic fallback shows.
* Finding #233 — the "posting(s)" parenthetical plural in the run-complete
  toast is now a real singular/plural branch.
* Finding #207 — the "Engine offline" banner badge is now "Not connected",
  matching the same fix already landed in applicantGallery.js.
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
JS_DIR = REPO_ROOT / "workspace" / "static" / "js"
DEBUG_JS = JS_DIR / "applicantDebug.js"

_HAS_NODE = shutil.which("node") is not None


@pytest.fixture(scope="module")
def node_available():
    if not _HAS_NODE:
        pytest.skip("node binary not on PATH")


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _find_function(src: str, name: str) -> str:
    """Extract a top-level `function name(...) { ... }` body via brace
    counting (mirrors test_applicant_copy_voice_02_documents_digest.py's
    helper)."""
    m = re.search(rf"function {re.escape(name)}\([^)]*\)\s*\{{", src)
    assert m, f"expected to find function {name}"
    start = m.end()
    depth = 1
    i = start
    while depth > 0:
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
        i += 1
    return src[start : i - 1]


def test_node_check_applicant_debug_js(node_available):
    res = subprocess.run(["node", "--check", str(DEBUG_JS)], capture_output=True, timeout=15, text=True)
    assert res.returncode == 0, f"node --check failed:\n{res.stderr}"


def test_ask_assistant_tooltip_names_one_surface_not_two():
    """Finding #236 — the tooltip used to switch from "the assistant" to
    "the agent" mid-sentence; it must now name the Job Assistant once."""
    src = _read(DEBUG_JS)
    assert 'title="Open the assistant beside this so you can ask about what the agent is doing"' not in src
    assert "Job Assistant" in src
    assert 'title="Open the Job Assistant beside this window to ask about what\'s happening"' in src


def test_download_audit_log_error_toast_drops_raw_message():
    """Finding #221 — the raw HTTP-status / server-text error must not reach
    the toast; only the calm, plain-language fallback should show."""
    body = _find_function(_read(DEBUG_JS), "_downloadAuditLog")
    assert re.search(r"catch\s*\(e\)\s*\{\s*_toast\('Could not download the activity log right now\.'\);", body), (
        "expected the catch block to always show the plain-language message"
    )
    assert "_toast(e.message" not in body


def test_insights_conversion_note_uses_american_spelling():
    """Finding #234 — the only -our spelling in the product."""
    src = _read(DEBUG_JS)
    assert "favour" not in src
    assert "which sources and roles to favor next" in src


def test_variant_approval_state_is_in_review_not_awaiting():
    """Finding #238."""
    body = _find_function(_read(DEBUG_JS), "_renderVariants")
    assert "'awaiting review'" not in body
    assert "'in review'" in body


def test_run_now_explainer_says_daily_updates_not_digest():
    """Finding #222 — the surface is called Daily updates, not "the digest"."""
    src = _read(DEBUG_JS)
    assert "refreshes the digest" not in src
    assert "refreshes your Daily updates" in src


def test_run_target_note_drops_clamped_jargon():
    """Finding #224."""
    src = _read(DEBUG_JS)
    assert "are clamped automatically" not in src
    assert "are lowered to the cap automatically" in src


def test_run_now_skip_reason_never_shows_raw_machine_value():
    """Finding #220 — the raw ``res.reason`` enum (e.g. "prefill_locked")
    must never itself reach the toast; only the mapped label or the
    generic fallback can."""
    src = _read(DEBUG_JS)
    assert not re.search(r"_SKIP_REASON_LABELS\[res\.reason\]\s*\|\|\s*res\.reason\s*\|\|", src), (
        "raw res.reason must not be a toast fallback"
    )
    assert "_SKIP_REASON_LABELS[res.reason] || 'Nothing to run right now.'" in src


def test_run_now_found_count_uses_real_plural():
    """Finding #233 — no bare "(s)" parenthetical plural."""
    src = _read(DEBUG_JS)
    assert "posting(s)" not in src
    assert "res.discovered === 1 ? 'posting' : 'postings'" in src


def test_engine_banner_says_not_connected():
    """Finding #207 — matches the fix already landed in applicantGallery.js
    (finding #207 there too)."""
    fn = re.search(r"function _setEngineBanner\(modal, up\)\s*\{(.*?)\n\}", _read(DEBUG_JS), re.S)
    assert fn, "expected _setEngineBanner"
    assert "Engine offline" not in fn.group(1)
    assert "Not connected" in fn.group(1)


# ── Denylist hygiene (per the task's standing instruction) ──────────────────

#: The four upstream-fork codenames CI's repo-wide white-label denylist step
#: bans from shipped artifacts. Split into two-piece tuples so the literal,
#: contiguous codename string never appears in this file's own source text.
_DENYLIST_CODENAME_HALVES = (
    ("fire", "house"),
    ("or", "well"),
    ("odys", "seus"),
    ("smo", "key"),
)


def test_new_test_file_is_denylist_clean():
    text = pathlib.Path(__file__).read_text(encoding="utf-8").lower()
    for a, b in _DENYLIST_CODENAME_HALVES:
        assert (a + b) not in text
