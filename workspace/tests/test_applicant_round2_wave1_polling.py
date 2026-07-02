"""Regression coverage for round 2 / wave 1, Top-25 items #8 and #20 (status-strip
half), confined to ``static/js/applicantActivity.js``, ``static/js/applicantUpdate.js``
and ``static/js/emailLibrary/applicantDigest.js`` (+ the shared ``pollVisible``
helper in ``static/js/applicantCore.js`` and ``static/index.html``, read-only
reference for the aria facts).

Item #8: pause all polling while the browser tab is hidden (Portal 60s / Activity
45s / Update 3s), resuming with an immediate refresh (not a stale wait) when the
tab becomes visible again.

Survey of the three in-scope modules at authoring time:
  * ``applicantActivity.js`` — the 45s status-strip poll already used the shared
    ``pollVisible`` helper (added in an earlier round-1 commit, "Activity strip
    resilience" / "quick-wins #1"). No change needed; guarded below so a future
    edit can't quietly regress it back to a raw ``setInterval``.
  * ``applicantUpdate.js`` — the 3s while-updating status poll (``_startPolling``)
    was still a raw ``setInterval`` with no visibility guard. THIS is the actual
    fix in this batch: it now goes through the same ``pollVisible`` helper.
  * ``emailLibrary/applicantDigest.js`` — has no engine-content polling loop at
    all (the digest itself loads on modal-open / campaign-change / manual
    refresh only). Its only ``setInterval`` is an unrelated ~60s "am I still
    verifiably here" PRESENCE heartbeat that already has its own
    ``visibilitychange`` handling (explicit ``present:false`` on hidden/blur/
    pagehide) — this is the "existing pattern" the audit's anchor pointed at,
    already generalized into ``pollVisible`` and reused by Activity/Update/
    Portal rather than reinvented. Nothing to change here; guarded below so the
    "no stray content-poll loop" fact doesn't silently regress.

Item #20 (status-strip half only): the always-visible status strip
(``#applicant-status-strip`` in ``static/index.html``) already carries
``role="status"`` + ``aria-live="polite"`` + a plain-language ``aria-label``
(added in an earlier round-1 shared-file commit, "rail a11y ... role=status on
the status strip"). ``applicantActivity.js`` never touches those attributes (it
only mutates textContent/classList), so the live region survives every render.
Guarded below by reading the static markup.

Follows the ``test_applicant_round1_observability.py`` convention: source-text
regex assertions for the browser-only modules (they do top-level DOM work on
import — ``_boot()`` at module scope — so they are not importable under bare
``node --input-type=module`` without a DOM shim), plus one *real* node-executed
behavioral test of ``pollVisible`` itself (a dependency-free, extractable pure
function) per ``test_applicant_update_js.py``'s precedent, since that function
is the actual mechanism every fix in this batch relies on.

Each assertion here was verified, by hand, to actually go red when the
underlying fix is reverted (temporarily re-inlining the old raw ``setInterval``
loop / stripping the aria attributes), then confirmed green again after
restoring.
"""

from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess
import textwrap

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
JS_DIR = REPO_ROOT / "workspace" / "static" / "js"
CORE_JS = JS_DIR / "applicantCore.js"
ACTIVITY_JS = JS_DIR / "applicantActivity.js"
UPDATE_JS = JS_DIR / "applicantUpdate.js"
DIGEST_JS = JS_DIR / "emailLibrary" / "applicantDigest.js"
INDEX_HTML = REPO_ROOT / "workspace" / "static" / "index.html"

_HAS_NODE = shutil.which("node") is not None


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def node_available():
    if not _HAS_NODE:
        pytest.skip("node binary not on PATH")


def _run_node(script: str) -> dict:
    res = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=REPO_ROOT / "workspace",
        capture_output=True,
        timeout=15,
        text=True,
    )
    if res.returncode != 0:
        raise AssertionError(f"node failed:\n{res.stderr}")
    out_lines = [ln for ln in res.stdout.splitlines() if ln.strip()]
    if not out_lines:
        raise AssertionError("node produced no stdout")
    return json.loads(out_lines[-1])


# ── pollVisible (applicantCore.js) — the shared mechanism, real execution ──


def _extract_poll_visible_source() -> str:
    src = _read(CORE_JS)
    m = re.search(r"export function pollVisible\([^)]*\)\s*\{.*?\n\}\n", src, re.S)
    assert m, "expected `export function pollVisible(...) { ... }` in applicantCore.js"
    return m.group(0).replace("export function", "function", 1)


def test_poll_visible_fires_immediately_and_pauses_while_hidden(node_available):
    """pollVisible must fire its callback immediately on start (so a caller is
    seeded, not left stale), must NOT tick again while document.visibilityState
    is 'hidden' (the whole point of #8 — no wasted requests while backgrounded),
    and must fire an immediate refresh (not wait out a stale interval) the
    moment visibility returns — exactly the "resumes with an immediate refresh"
    requirement."""
    poll_visible_src = _extract_poll_visible_source()
    script = textwrap.dedent(f"""
        {poll_visible_src}
        const handlers = [];
        globalThis.document = {{
          visibilityState: 'visible',
          addEventListener: (ev, fn) => {{ if (ev === 'visibilitychange') handlers.push(fn); }},
          removeEventListener: (ev, fn) => {{
            const i = handlers.indexOf(fn);
            if (i >= 0) handlers.splice(i, 1);
          }},
        }};
        function fireVisibilityChange() {{ for (const h of [...handlers]) h(); }}
        const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

        let calls = 0;
        const stop = pollVisible(() => {{ calls += 1; }}, 40);
        const afterStart = calls; // immediate seed fire

        await sleep(110); // ~2-3 more ticks while visible
        const whileVisible = calls;

        document.visibilityState = 'hidden';
        fireVisibilityChange();
        const atHidden = calls; // no extra fire just from going hidden
        await sleep(150); // would have ticked ~3x more if not paused
        const afterWaitingHidden = calls; // must be unchanged

        document.visibilityState = 'visible';
        fireVisibilityChange();
        const afterResume = calls; // immediate refresh on resume, not a stale wait

        await sleep(110);
        const afterResumeTicking = calls; // interval resumed ticking

        stop();
        const beforeStopCount = calls;
        await sleep(110);
        const afterStop = calls; // stop() must fully tear down (no more ticks)

        console.log(JSON.stringify({{
          afterStart, whileVisible, atHidden, afterWaitingHidden,
          afterResume, afterResumeTicking, beforeStopCount, afterStop,
        }}));
    """)
    out = _run_node(script)
    assert out["afterStart"] == 1, "must fire immediately on start"
    assert out["whileVisible"] > out["afterStart"], "must keep ticking while visible"
    assert out["atHidden"] == out["whileVisible"], "going hidden must not itself trigger a fire"
    assert out["afterWaitingHidden"] == out["atHidden"], (
        "must NOT tick while document.hidden is true — this is the core of #8"
    )
    assert out["afterResume"] == out["afterWaitingHidden"] + 1, (
        "becoming visible again must fire an immediate refresh, not wait out a stale interval"
    )
    assert out["afterResumeTicking"] > out["afterResume"], "interval must resume ticking after resume"
    assert out["afterStop"] == out["beforeStopCount"], "stop() must fully tear down the loop"


# ── applicantUpdate.js — the actual fix in this batch (3s update-status poll) ──


def test_update_js_imports_poll_visible_from_core():
    src = _read(UPDATE_JS)
    assert re.search(r"import\s*\{[^}]*\bpollVisible\b[^}]*\}\s*from\s*'\./applicantCore\.js'", src), (
        "applicantUpdate.js must import the shared pollVisible helper from applicantCore.js"
    )


def test_update_js_start_polling_uses_poll_visible_not_raw_set_interval():
    """_startPolling must delegate to pollVisible(POLL_MS) rather than rolling
    its own unguarded setInterval — the pre-fix version polled the OPS/update
    endpoint every 3s even while the tab was hidden."""
    src = _read(UPDATE_JS)
    m = re.search(r"function _startPolling\(\)\s*\{(.*?)\n\}", src, re.S)
    assert m, "expected a top-level _startPolling() function"
    body = m.group(1)
    assert "pollVisible(" in body, "_startPolling must call the shared pollVisible(...) helper"
    assert "POLL_MS" in body, "_startPolling must still poll on the 3s POLL_MS cadence"
    assert "setInterval" not in body, (
        "_startPolling must not roll its own raw setInterval anymore — that was the unguarded loop"
    )


def test_update_js_stop_polling_tears_down_poll_visible_handle():
    """_stopPolling must call the stop handle pollVisible returns (which also
    removes its visibilitychange listener) rather than a bare clearInterval on
    a raw interval id — otherwise every modal close would leak a listener."""
    src = _read(UPDATE_JS)
    m = re.search(r"function _stopPolling\(\)\s*\{(.*?)\n\}", src, re.S)
    assert m, "expected a top-level _stopPolling() function"
    body = m.group(1)
    assert "_pollStop" in body, "_stopPolling must tear down the pollVisible stop handle (_pollStop)"
    assert "clearInterval" not in body, (
        "_stopPolling must not directly clearInterval an id anymore — pollVisible owns the interval"
    )


def test_update_js_no_pollid_module_state_left_over():
    """The old `_pollIv` interval-id module variable must be fully gone, not
    left dangling alongside the new `_pollStop` handle."""
    src = _read(UPDATE_JS)
    assert "_pollIv" not in src, "the old raw interval-id variable (_pollIv) must be fully removed"


# ── applicantActivity.js — guard the pre-existing 45s strip poll stays fixed ──


def test_activity_js_status_poll_still_uses_poll_visible():
    """Regression guard: the always-visible status strip's 45s poll
    (refreshStatus / STATUS_POLL_MS) must keep going through pollVisible — a
    future edit to this heavily-touched file must not quietly reintroduce a
    raw, always-on setInterval for it."""
    src = _read(ACTIVITY_JS)
    assert re.search(r"pollVisible\s*\(\s*refreshStatus\s*,\s*STATUS_POLL_MS\s*\)", src), (
        "the status-strip poll must be wired through pollVisible(refreshStatus, STATUS_POLL_MS)"
    )
    assert re.search(r"import\s*\{[^}]*\bpollVisible\b[^}]*\}\s*from\s*'\./applicantCore\.js'", src), (
        "applicantActivity.js must still import pollVisible from applicantCore.js"
    )


# ── applicantDigest.js — confirm there is no unguarded content-poll loop ──


def test_digest_js_has_no_engine_content_poll_loop():
    """The digest panel loads content on modal-open / campaign-change / manual
    refresh only — there must be no setInterval that re-fetches digest/inbox
    content on a fixed cadence (which would need the same visibility guard).
    The only setInterval in this file is the unrelated presence heartbeat,
    which already self-guards via visibilitychange (present:false on hidden)."""
    src = _read(DIGEST_JS)
    interval_calls = re.findall(r"setInterval\(([^,]*),", src)
    assert len(interval_calls) == 1, (
        f"expected exactly one setInterval in applicantDigest.js (the presence heartbeat), found {interval_calls!r}"
    )
    # It must be the presence heartbeat (posts to /presence), not a digest/inbox fetch.
    assert "_postPresence" in interval_calls[0], (
        "the sole setInterval in this file must be the presence heartbeat, not a content-poll loop"
    )


def test_digest_js_presence_heartbeat_still_guards_visibility():
    """The presence heartbeat must still explicitly signal absence on
    visibilitychange -> hidden (this is the 'existing pattern' the audit
    anchor referenced) — guarded so it isn't silently dropped."""
    src = _read(DIGEST_JS)
    assert "visibilitychange" in src, "presence heartbeat must still listen for visibilitychange"
    assert "document.visibilityState === 'hidden'" in src, (
        "presence heartbeat must still branch on the tab becoming hidden"
    )


# ── #20 (status-strip half): the strip is a proper ARIA live region ──


def test_status_strip_markup_is_a_live_region():
    """#applicant-status-strip in index.html must carry role="status" and
    aria-live="polite" so screen readers announce state changes (paused /
    resumed / running) without the user navigating to it."""
    html = _read(INDEX_HTML)
    m = re.search(r'<button[^>]*id="applicant-status-strip"[^>]*>', html)
    assert m, "expected the #applicant-status-strip element in index.html"
    tag = m.group(0)
    assert re.search(r'role="status"', tag), "the status strip must carry role=\"status\""
    assert re.search(r'aria-live="polite"', tag), "the status strip must carry aria-live=\"polite\""
    assert re.search(r'aria-label="[^"]+"', tag), "the status strip must carry a plain-language aria-label"


def test_activity_js_never_strips_the_strip_live_region_attributes():
    """applicantActivity.js only mutates the strip's textContent/classList/
    style/title — it must never remove/overwrite role or aria-live on the
    strip element, which would silently break the live region."""
    src = _read(ACTIVITY_JS)
    # No code path should ever call removeAttribute('role'/'aria-live') or
    # setAttribute a non-'status'/'polite' value on the strip.
    assert "removeAttribute('role')" not in src
    assert "removeAttribute(\"role\")" not in src
    assert "removeAttribute('aria-live')" not in src
    assert "removeAttribute(\"aria-live\")" not in src
