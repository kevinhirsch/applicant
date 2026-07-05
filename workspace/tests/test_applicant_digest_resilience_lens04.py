"""Regression coverage for docs/design/audits/exhaustive2/04_failure_paths.md
findings #53, #60, #64 and #67, all confined to a single file:
``workspace/static/js/emailLibrary/applicantDigest.js``.

Four independent resilience gaps in the digest panel:

* **#53** — ``_onPass`` (the Pass/decline flow) asked for a reason via
  ``styledPrompt``, then threw it away the moment the prompt resolved,
  regardless of whether the follow-up POST actually succeeded. A flaky
  ``/applications/{id}/decline`` call forced the user to retype the same
  reason from scratch. Fix: a module-level ``_lastDeclineReasonByRow`` map
  preserves the typed reason, keyed by row id, across a FAILED submit, and
  prefills the next ``styledPrompt`` call (``defaultValue``) so a retry never
  starts from a blank box. It is only cleared once the decline actually goes
  through.

* **#60** — the manual "Research" button's click handler (``_onResearch``)
  had no client-side ceiling and no way to bail out: a hung engine call left
  the button stuck on "Researching…" forever. Fix: an ``AbortController``
  bounds the call to ``RESEARCH_TIMEOUT_MS`` (a generous ceiling, since the
  engine's own request layer deliberately exempts research from its shared
  45s timeout — see "Exempt internal research from the 45s timeout"), and
  the SAME button doubles as a cancel control (``_cancelResearch``) while a
  run is in flight, tracked via ``btn.dataset.researching``.

* **#64** — the presence heartbeat's ``window`` ``blur`` handler posted
  ``present:false`` unconditionally, even when focus only moved WITHIN the
  page (e.g. into the email-preview modal's iframe) rather than genuinely
  away from the tab. Fix: the blur handler now defers one tick and re-checks
  ``document.visibilityState``/``document.hasFocus()`` before reporting
  absence — ``hasFocus()`` reports true whenever focus is still anywhere in
  the document (including same-origin iframes), so a same-page focus shift
  no longer flips presence to false.

* **#67** — ``_emailSectionActive`` memoized its feature-gate promise for the
  entire page session with no expiry, so a mid-session config change (e.g.
  finishing setup) was never picked up without a hard reload. Fix: a
  ``_FEATURE_CACHE_TTL_MS`` TTL plus a ``_featurePromiseAt`` timestamp make
  the cache re-check periodically instead of memoizing forever.

Each assertion below was verified, by hand, to go RED against a backup of the
pre-fix file (``cp`` of the file at the commit before this series landed) and
GREEN again against the fixed file, per this series' standing DoD.
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
DIGEST_JS = JS_DIR / "emailLibrary" / "applicantDigest.js"

_HAS_NODE = shutil.which("node") is not None


def _read() -> str:
    return DIGEST_JS.read_text(encoding="utf-8")


def _extract(src: str, pattern: str, label: str) -> str:
    m = re.search(pattern, src, re.S)
    assert m, f"expected to find {label} in {DIGEST_JS}"
    return m.group(0)


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
    assert res.returncode == 0, f"node failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    out_lines = [ln for ln in res.stdout.splitlines() if ln.strip()]
    assert out_lines, "node produced no stdout"
    return json.loads(out_lines[-1])


def test_node_check_applicant_digest_js(node_available):
    """Syntax smoke: the module every assertion below reads from must parse."""
    res = subprocess.run(
        ["node", "--check", str(DIGEST_JS)],
        capture_output=True,
        timeout=15,
        text=True,
    )
    assert res.returncode == 0, f"node --check failed:\n{res.stderr}"


# ── #53 — decline reason survives a failed POST ─────────────────────────────


def test_decline_reason_cache_exists():
    src = _read()
    assert re.search(r"const _lastDeclineReasonByRow\s*=\s*new Map\(\);", src), (
        "expected a module-level _lastDeclineReasonByRow Map to preserve a "
        "decline reason across a failed submit"
    )


def test_on_pass_prefills_from_and_writes_to_the_reason_cache():
    src = _read()
    on_pass = _extract(src, r"async function _onPass\(.*?\n\}\n", "_onPass")
    assert re.search(r"_lastDeclineReasonByRow\.get\(id\)", on_pass), (
        "_onPass must read any previously preserved reason for this row before prompting"
    )
    assert re.search(r"defaultValue:\s*priorReason", on_pass), (
        "the preserved reason must be threaded into styledPrompt's defaultValue "
        "so a retry starts prefilled, not blank"
    )
    # Order matters: only a FAILED submit should preserve the reason; a
    # SUCCESSFUL submit should delete it. Verify both calls exist in the
    # expected try/catch halves.
    assert re.search(r"await _api\(`/applications/.*?/decline`", on_pass, re.S)
    try_idx = on_pass.index("try {")
    catch_idx = on_pass.index("} catch")
    delete_idx = on_pass.index("_lastDeclineReasonByRow.delete(id)")
    set_idx = on_pass.index("_lastDeclineReasonByRow.set(id,")
    assert try_idx < delete_idx < catch_idx, (
        "the cache must be CLEARED inside the success path (inside try, before catch)"
    )
    assert set_idx > catch_idx, (
        "the cache must be WRITTEN only inside the failure path (inside catch)"
    )


def test_decline_reason_preserved_on_failure_and_cleared_on_success(node_available):
    """Real execution: a row's first decline attempt fails after a reason is
    typed; the SAME row's next attempt must be prefilled with that exact
    reason. Once the retry's POST succeeds, the cache must be empty again."""
    src = _read()
    row_action_id_fn = _extract(src, r"function _rowActionId\(row\)\s*\{.*?\n\}\n", "_rowActionId")
    cache_decl = _extract(
        src, r"const _lastDeclineReasonByRow\s*=\s*new Map\(\);", "_lastDeclineReasonByRow declaration"
    )
    on_pass_fn = _extract(src, r"async function _onPass\(.*?\n\}\n", "_onPass")

    script = textwrap.dedent(f"""
        const promptCalls = [];
        async function styledPrompt(message, opts) {{
          promptCalls.push(opts.defaultValue || '');
          // Simulate the user re-submitting whatever was prefilled (or typing
          // fresh on the very first attempt).
          return promptCalls.length === 1 ? 'too junior for this one' : opts.defaultValue;
        }}
        const toasts = [];
        function showToast(msg) {{ toasts.push(msg); }}
        function _disableRow(card) {{}}
        function _fadeOutRow(card) {{}}

        let apiCalls = 0;
        async function _api(path, opts) {{
          apiCalls += 1;
          if (apiCalls === 1) {{
            const e = new Error('That did not go through (error 500).');
            e.status = 500;
            throw e;
          }}
          return {{ ok: true }};
        }}

        {row_action_id_fn}
        {cache_decl}
        {on_pass_fn}

        (async () => {{
          const row = {{ id: 'row-1' }};
          const card = {{ querySelectorAll: () => [] }};
          const btn = {{}};
          await _onPass(card, row, btn, null);  // fails after the reason is typed
          const afterFailure = _lastDeclineReasonByRow.get('row-1') || null;
          await _onPass(card, row, btn, null);  // retry succeeds
          const afterSuccess = _lastDeclineReasonByRow.has('row-1');
          console.log(JSON.stringify({{ promptCalls, toasts, afterFailure, afterSuccess, apiCalls }}));
        }})();
    """)
    out = _run_node(script)
    assert out["promptCalls"][0] == "", "the first-ever attempt has nothing to prefill"
    assert out["afterFailure"] == "too junior for this one", (
        "the typed reason must be preserved after the POST fails"
    )
    assert out["promptCalls"][1] == "too junior for this one", (
        "the retry's prompt must be prefilled with the preserved reason, not blank"
    )
    assert out["afterSuccess"] is False, "the cache must be cleared once the decline actually succeeds"
    assert out["apiCalls"] == 2


# ── #60 — research run: client-side timeout + cancel affordance ────────────


def test_research_timeout_constant_is_generous_but_finite():
    src = _read()
    m = re.search(r"const RESEARCH_TIMEOUT_MS\s*=\s*(\d+);", src)
    assert m, "expected a RESEARCH_TIMEOUT_MS constant bounding a research run"
    ms = int(m.group(1))
    assert 60_000 <= ms <= 180_000, (
        "the ceiling must be generous (the engine exempts research from its "
        "shared 45s timeout on purpose) but still finite"
    )


def test_on_research_uses_an_abort_controller_and_cancel_helper():
    src = _read()
    on_research = _extract(src, r"async function _onResearch\(.*?\n\}\n", "_onResearch")
    assert "new AbortController()" in on_research, (
        "_onResearch must build an AbortController to bound/cancel the call"
    )
    assert "setTimeout(" in on_research and "RESEARCH_TIMEOUT_MS" in on_research, (
        "_onResearch must set a timeout that aborts the run"
    )
    assert "controller.signal" in on_research, "the abort signal must be threaded into the fetch calls"
    assert re.search(r"function _cancelResearch\(btn\)\s*\{.*?\.abort\(\)", src, re.S), (
        "expected a _cancelResearch(btn) helper that aborts the in-flight run"
    )
    # The button doubles as its own cancel control: a click routed to
    # _onResearch while a run is already in flight for the SAME button must
    # cancel it, not start an overlapping second run. This must live inside
    # _onResearch itself (not the click wiring), since the pinned wiring
    # test (test_applicant_round2_wave3_employerintel.py) requires the click
    # handler to stay a plain `() => _onResearch(...)` call.
    assert re.search(r"btn\.dataset\.researching === '1'", on_research), (
        "_onResearch must check whether THIS button already has a run in flight"
    )
    assert "_cancelResearch(btn)" in on_research, (
        "a click while busy must cancel via _cancelResearch(btn), not restart"
    )
    click_wire = _extract(
        src,
        r"research\.addEventListener\('click', \(\) => _onResearch\(.*?\);",
        "the Research button's click wiring",
    )
    assert "getCampaignId(), row, research" in click_wire, (
        "the click handler itself must stay untouched — always calls _onResearch, "
        "which now owns the busy/cancel decision"
    )


def test_second_click_while_a_run_is_in_flight_cancels_it(node_available):
    """Real execution: calling _onResearch a SECOND time for the same button
    while its first call is still in flight must cancel that run (mirrors a
    user re-clicking Research while it says "Researching…"), not start an
    overlapping second request."""
    src = _read()
    timeout_line = _extract(src, r"const RESEARCH_TIMEOUT_MS\s*=\s*\d+;", "RESEARCH_TIMEOUT_MS")
    runs_map_line = _extract(src, r"const _researchRuns = new WeakMap\(\);.*?\n", "_researchRuns")
    cancel_fn = _extract(src, r"function _cancelResearch\(btn\)\s*\{.*?\n\}\n", "_cancelResearch")
    api_research_fn = _extract(src, r"async function _apiResearch\(.*?\n\}\n", "_apiResearch")
    api_cached_fn = _extract(src, r"async function _apiResearchCached\(.*?\n\}\n", "_apiResearchCached")
    query_fn = _extract(src, r"function _researchQuery\(row\)\s*\{.*?\n\}\n", "_researchQuery")
    on_research_fn = _extract(src, r"async function _onResearch\(.*?\n\}\n", "_onResearch")

    script = textwrap.dedent(f"""
        const API_BASE = '';
        const _ICON_SEARCH = '';
        const toasts = [];
        function showToast(msg) {{ toasts.push(msg); }}
        function _showReport() {{ throw new Error('must not be reached when cancelled'); }}

        let fetchCalls = 0;
        globalThis.fetch = (url, opts) => {{
          fetchCalls += 1;
          return new Promise((resolve, reject) => {{
            if (opts && opts.signal) {{
              opts.signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
            }}
          }});
        }};

        {timeout_line}
        {runs_map_line}
        {cancel_fn}
        {api_research_fn}
        {api_cached_fn}
        {query_fn}
        {on_research_fn}

        (async () => {{
          const btn = {{ innerHTML: 'Research', title: 'orig title', dataset: {{}} }};
          const row = {{ title: 'Backend Engineer', company: 'Acme' }};
          const firstRun = _onResearch('c1', row, btn);  // click #1: starts a run
          await new Promise((r) => setTimeout(r, 15));
          const wasResearching = btn.dataset.researching === '1';
          await _onResearch('c1', row, btn);             // click #2 (same button): must cancel, not restart
          await firstRun;
          console.log(JSON.stringify({{
            wasResearching,
            toasts,
            fetchCalls,
            researchingFlagLeftSet: btn.dataset.researching === '1',
          }}));
        }})();
    """)
    out = _run_node(script)
    assert out["wasResearching"] is True
    assert any("cancel" in t.lower() for t in out["toasts"]), (
        f"expected a cancellation message, got {out['toasts']!r}"
    )
    assert out["fetchCalls"] == 1, "the second click must NOT fire an overlapping second fetch"
    assert out["researchingFlagLeftSet"] is False


def test_research_run_times_out_and_restores_the_button(node_available):
    """Real execution: a fetch that never resolves must still cause
    _onResearch to give up after its timeout, show a clear message, and put
    the button back to its original, clickable state."""
    src = _read()
    timeout_line = _extract(src, r"const RESEARCH_TIMEOUT_MS\s*=\s*\d+;", "RESEARCH_TIMEOUT_MS")
    fast_timeout_line = re.sub(r"\d+", "40", timeout_line)  # 40ms instead of the real ceiling, for a fast test
    runs_map_line = _extract(src, r"const _researchRuns = new WeakMap\(\);.*?\n", "_researchRuns")
    cancel_fn = _extract(src, r"function _cancelResearch\(btn\)\s*\{.*?\n\}\n", "_cancelResearch")
    api_research_fn = _extract(src, r"async function _apiResearch\(.*?\n\}\n", "_apiResearch")
    api_cached_fn = _extract(src, r"async function _apiResearchCached\(.*?\n\}\n", "_apiResearchCached")
    query_fn = _extract(src, r"function _researchQuery\(row\)\s*\{.*?\n\}\n", "_researchQuery")
    on_research_fn = _extract(src, r"async function _onResearch\(.*?\n\}\n", "_onResearch")

    script = textwrap.dedent(f"""
        const API_BASE = '';
        const _ICON_SEARCH = '';
        const toasts = [];
        function showToast(msg) {{ toasts.push(msg); }}
        function _showReport() {{ throw new Error('must not be reached in a timeout'); }}

        {fast_timeout_line}
        {runs_map_line}
        {cancel_fn}
        {api_research_fn}
        {api_cached_fn}
        {query_fn}
        {on_research_fn}

        // A fetch that never resolves on its own, but rejects if its signal aborts —
        // exactly how a real hung request behaves once the browser gives up on it.
        globalThis.fetch = (url, opts) => new Promise((resolve, reject) => {{
          if (opts && opts.signal) {{
            opts.signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
          }}
        }});

        (async () => {{
          const btn = {{ innerHTML: 'Research', title: 'orig title', dataset: {{}} }};
          const row = {{ title: 'Backend Engineer', company: 'Acme' }};
          const start = Date.now();
          await _onResearch('c1', row, btn);
          const elapsedMs = Date.now() - start;
          console.log(JSON.stringify({{
            elapsedMs,
            toasts,
            researchingFlagLeftSet: btn.dataset.researching === '1',
            finalInnerHTML: btn.innerHTML,
            finalTitle: btn.title,
          }}));
        }})();
    """)
    out = _run_node(script)
    assert out["elapsedMs"] < 2000, "the timeout must actually fire, not hang for the test's 15s cap"
    assert any("too long" in t for t in out["toasts"]), (
        f"expected a 'taking too long' style message, got {out['toasts']!r}"
    )
    assert out["researchingFlagLeftSet"] is False, "the busy flag must be cleared once the run gives up"
    assert out["finalInnerHTML"] == "Research", "the button must be restored to its original label"
    assert out["finalTitle"] == "orig title", "the button must be restored to its original title"


def test_research_run_cancelled_mid_flight_by_a_second_click(node_available):
    """Real execution: clicking Research again while a run is in flight must
    cancel it immediately (not wait out the timeout), via _cancelResearch."""
    src = _read()
    real_timeout_line = _extract(src, r"const RESEARCH_TIMEOUT_MS\s*=\s*\d+;", "RESEARCH_TIMEOUT_MS")
    runs_map_line = _extract(src, r"const _researchRuns = new WeakMap\(\);.*?\n", "_researchRuns")
    cancel_fn = _extract(src, r"function _cancelResearch\(btn\)\s*\{.*?\n\}\n", "_cancelResearch")
    api_research_fn = _extract(src, r"async function _apiResearch\(.*?\n\}\n", "_apiResearch")
    api_cached_fn = _extract(src, r"async function _apiResearchCached\(.*?\n\}\n", "_apiResearchCached")
    query_fn = _extract(src, r"function _researchQuery\(row\)\s*\{.*?\n\}\n", "_researchQuery")
    on_research_fn = _extract(src, r"async function _onResearch\(.*?\n\}\n", "_onResearch")

    script = textwrap.dedent(f"""
        const API_BASE = '';
        const _ICON_SEARCH = '';
        const toasts = [];
        function showToast(msg) {{ toasts.push(msg); }}
        function _showReport() {{ throw new Error('must not be reached when cancelled'); }}

        {real_timeout_line}
        {runs_map_line}
        {cancel_fn}
        {api_research_fn}
        {api_cached_fn}
        {query_fn}
        {on_research_fn}

        globalThis.fetch = (url, opts) => new Promise((resolve, reject) => {{
          if (opts && opts.signal) {{
            opts.signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
          }}
        }});

        (async () => {{
          const btn = {{ innerHTML: 'Research', title: 'orig title', dataset: {{}} }};
          const row = {{ title: 'Backend Engineer', company: 'Acme' }};
          const runPromise = _onResearch('c1', row, btn);
          await new Promise((r) => setTimeout(r, 15));
          const wasResearching = btn.dataset.researching === '1';
          _cancelResearch(btn);  // simulates a second click on the same button
          await runPromise;
          console.log(JSON.stringify({{
            wasResearching,
            toasts,
            researchingFlagLeftSet: btn.dataset.researching === '1',
          }}));
        }})();
    """)
    out = _run_node(script)
    assert out["wasResearching"] is True, "the button must flag itself busy while a run is in flight"
    assert any("cancel" in t.lower() for t in out["toasts"]), (
        f"expected a cancellation message, got {out['toasts']!r}"
    )
    assert out["researchingFlagLeftSet"] is False


# ── #64 — presence heartbeat: blur only reports absent on a REAL focus loss ─


def test_blur_no_longer_wired_directly_to_leave():
    """Regression guard: the pre-fix code wired `window.addEventListener('blur',
    leave)` directly — any accidental revert back to that must fail here."""
    src = _read()
    assert "window.addEventListener('blur', leave)" not in src, (
        "blur must not report absence directly/unconditionally any more"
    )
    assert "window.addEventListener('blur', onBlur)" in src, (
        "blur must go through the guarded onBlur handler"
    )


def test_on_blur_rechecks_focus_and_visibility_before_reporting_absent():
    src = _read()
    signal_presence = _extract(src, r"function _signalPresence\(\)\s*\{.*?\n\}\n", "_signalPresence")
    on_blur = _extract(signal_presence, r"const onBlur = \(\) => \{.*?\n    \};\n", "onBlur")
    assert "setTimeout(" in on_blur, "onBlur must defer its recheck (focus settles a tick later)"
    assert "document.hasFocus" in on_blur, "onBlur must recheck document.hasFocus() before reporting absent"
    assert "document.visibilityState" in on_blur, "onBlur must also defer to the visibilitychange path"
    assert "leave()" in on_blur


def test_presence_blur_behaviour_real_execution(node_available):
    """Real execution against a fake document/window: a blur where
    document.hasFocus() still reports true (focus moved within the same
    document, e.g. into an iframe) must NOT report absence; a blur where
    hasFocus() reports false must."""
    src = _read()
    state_decls = _extract(
        src,
        r"let _presenceTimer = null;.*?let _freshnessPanel = null;\n",
        "presence module state",
    )
    post_presence_fn = _extract(src, r"function _postPresence\(present\)\s*\{.*?\n\}\n", "_postPresence")
    mark_activity_fn = _extract(
        src, r"function _markPresenceActivity\(\).*?\n", "_markPresenceActivity"
    )
    is_here_fn = _extract(src, r"function _isVerifiablyHere\(\)\s*\{.*?\n\}\n", "_isVerifiablyHere")
    signal_presence_fn = _extract(src, r"function _signalPresence\(\)\s*\{.*?\n\}\n", "_signalPresence")

    script = textwrap.dedent(f"""
        const API_BASE = '';
        const presenceCalls = [];
        globalThis.fetch = async (url, opts) => {{
          presenceCalls.push(JSON.parse(opts.body).present);
          return {{ ok: true, json: async () => ({{}}) }};
        }};

        const listeners = {{}};
        let visibilityState = 'visible';
        let hasFocusValue = true;
        globalThis.document = {{
          get visibilityState() {{ return visibilityState; }},
          addEventListener: (ev, fn) => {{ (listeners[ev] = listeners[ev] || []).push(fn); }},
          removeEventListener: () => {{}},
          hasFocus: () => hasFocusValue,
          body: {{ contains: () => false }},
        }};
        globalThis.window = {{
          addEventListener: (ev, fn) => {{ (listeners[ev] = listeners[ev] || []).push(fn); }},
          removeEventListener: () => {{}},
        }};

        {state_decls}
        {post_presence_fn}
        {mark_activity_fn}
        {is_here_fn}
        {signal_presence_fn}

        function fire(ev) {{ for (const fn of (listeners[ev] || [])) fn(); }}
        const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

        (async () => {{
          _signalPresence();
          const afterStart = presenceCalls.length; // the immediate present:true seed

          // Focus only shifted within the page (e.g. into a same-page iframe):
          // hasFocus() still reports true.
          hasFocusValue = true;
          fire('blur');
          await sleep(20);
          const afterInnerBlur = presenceCalls.length;

          // A REAL focus loss: hasFocus() now reports false.
          hasFocusValue = false;
          fire('blur');
          await sleep(20);
          const afterRealBlur = presenceCalls.slice();

          process.exit(0);
        }})().then(() => {{}}, (e) => {{ console.error(e); process.exit(1); }});

        // Print right before the (synchronous-looking) exit above would fire —
        // reorganized below so we can actually see the values.
    """)
    # The IIFE above calls process.exit(0) before we get a chance to log, so
    # restructure: capture the values and print, THEN exit.
    script = script.replace(
        "          const afterRealBlur = presenceCalls.slice();\n\n          process.exit(0);",
        "          const afterRealBlur = presenceCalls.slice();\n"
        "          console.log(JSON.stringify({ afterStart, afterInnerBlur, afterRealBlur }));\n"
        "          process.exit(0);",
    )
    out = _run_node(script)
    assert out["afterStart"] == 1, "signalPresence must post an initial present:true"
    assert out["afterInnerBlur"] == out["afterStart"], (
        "a blur where document.hasFocus() is still true must NOT post another presence update"
    )
    assert out["afterRealBlur"][-1] is False, (
        "a blur where document.hasFocus() is false must report present:false"
    )


# ── #67 — feature-gate cache expires instead of memoizing forever ──────────


def test_feature_cache_ttl_constant_exists():
    src = _read()
    m = re.search(r"const _FEATURE_CACHE_TTL_MS\s*=\s*(\d+);", src)
    assert m, "expected a _FEATURE_CACHE_TTL_MS constant"
    ms = int(m.group(1))
    assert 0 < ms <= 10 * 60 * 1000, "the TTL should be short enough to pick up a mid-session change"


def test_email_section_active_checks_the_ttl_before_reusing_the_cache():
    src = _read()
    fn = _extract(src, r"async function _emailSectionActive\(\)\s*\{.*?\n\}\n", "_emailSectionActive")
    assert "_featurePromiseAt" in fn, "must track when the cached promise was created"
    assert re.search(r"_featurePromiseAt\s*\)\s*>\s*_FEATURE_CACHE_TTL_MS", fn), (
        "must compare elapsed time against the TTL before reusing _featurePromise"
    )


def test_feature_cache_expires_and_refetches_after_ttl(node_available):
    """Real execution with a controllable fake clock: a cache hit inside the
    TTL window must not re-fetch; once the fake clock advances past the TTL,
    the very next call must hit the network again and pick up a changed
    state."""
    src = _read()
    state_decl = _extract(
        src,
        r"let _featurePromise = null;\nlet _featurePromiseAt = 0;.*?const _FEATURE_CACHE_TTL_MS = \d+;\n",
        "feature-cache module state",
    )
    fn = _extract(src, r"async function _emailSectionActive\(\)\s*\{.*?\n\}\n", "_emailSectionActive")

    script = textwrap.dedent(f"""
        const API_BASE = '';
        let fakeNow = 1_000_000;
        Date.now = () => fakeNow;

        let fetchCalls = 0;
        const states = ['active', 'locked'];
        globalThis.fetch = async () => {{
          const state = states[Math.min(fetchCalls, states.length - 1)];
          fetchCalls += 1;
          return {{ ok: true, json: async () => ({{ sections: {{ email: {{ state }} }} }}) }};
        }};

        {state_decl}
        {fn}

        (async () => {{
          const first = await _emailSectionActive();       // fresh fetch -> 'active' -> true
          const second = await _emailSectionActive();      // still within TTL -> cache hit, no fetch
          const fetchCallsBeforeTtl = fetchCalls;
          fakeNow += 10 * 60 * 1000;                        // jump well past the TTL
          const third = await _emailSectionActive();        // TTL expired -> re-fetch -> 'locked' -> false
          console.log(JSON.stringify({{ first, second, third, fetchCallsBeforeTtl, fetchCallsAfter: fetchCalls }}));
        }})();
    """)
    out = _run_node(script)
    assert out["first"] is True
    assert out["second"] is True
    assert out["fetchCallsBeforeTtl"] == 1, (
        "a call within the TTL window must reuse the cached promise, not re-fetch"
    )
    assert out["third"] is False, "after the TTL expires, the next call must re-fetch and reflect the new state"
    assert out["fetchCallsAfter"] == 2, "the post-TTL call must have actually gone back to the network"
