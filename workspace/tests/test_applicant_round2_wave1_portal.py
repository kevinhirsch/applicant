"""Regression coverage for round 2, wave 1 of docs/design/audits/
PRODUCT_EXHAUSTIVE_AUDIT.md — the audit's own "Do this week (V:high*E:S)"
first tranche (Top-25 #10, #14, and the Portal half of #1/#8), confined to
workspace/static/js/applicantPortal.js.

Every fact below is read from the ACTUAL current source of that file (no
duplicated re-implementation of the logic under test), following the exact
two precedents already established for this file by
workspace/tests/test_applicant_round1_portal.py:

  * plain Python regex-over-source-text for markup/wiring facts (this file is
    not a pure leaf module — it touches `document`/`window`/`fetch` at import
    time, so a full module import under Node is impractical), and
  * extracting a REAL private function's source text out of the live file at
    test time and running it under `node --input-type=module` against a
    minimal fake `document`/DOM/`fetch`, so the pure logic under test is
    genuinely executed, not just pattern-matched.

Every assertion here was verified against a temporary revert of the
corresponding fix (edit -> rerun -> confirm a real AssertionError -> restore
via Edit/git) before being left in its final, passing form.

Covers:
  * Top-25 #10 - warm, time-aware Portal greeting (`_greetingLine`/`_partOfDay`,
    pre-existing) + the NEW "I'm on it" data half: `_agentPulseLine` /
    `_renderPulseLine` / `_loadAgentPulse`, sourced from the owner-scoped
    `/api/applicant/activity/snapshot` proxy (engine `now`/`next` sentences,
    e.g. an applied-today count), wired into `_renderEmpty` and `_load`.
  * Top-25 #14 - the header's persistent "What it never does" trust-contract
    affordance (`_toggleNeverDoesPanel`, pre-existing) + the NEW aria-expanded/
    aria-controls bookkeeping that makes the toggle accessible.
  * Top-25 #1/#8 (Portal's polling half only) - `_boot`'s badge-refresh poll is
    wired through the shared `pollVisible` helper (visibilitychange-guarded),
    not a raw `setInterval`, and re-booting stops the prior poll handle before
    starting a new one (pre-existing; locked in here since no test covered it).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent  # workspace/
PORTAL_JS = _REPO / "static" / "js" / "applicantPortal.js"
_HAS_NODE = shutil.which("node") is not None


@pytest.fixture(scope="module")
def node_available():
    if not _HAS_NODE:
        pytest.skip("node binary not on PATH")


def _portal_src() -> str:
    return PORTAL_JS.read_text(encoding="utf-8")


def _slice_between(src: str, start_marker: str, end_marker: str) -> str:
    start = src.index(start_marker)
    end = src.index(end_marker, start)
    return src[start:end]


def _run_node(script: str) -> dict:
    res = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=_REPO,
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


# ===========================================================================
# #10a - warm, time-aware greeting (_partOfDay / _greetingLine)
# ===========================================================================

def _greeting_block() -> str:
    src = _portal_src()
    return _slice_between(src, "function _partOfDay() {", "function _renderGreeting(pendingCount) {")


def test_greeting_line_is_time_aware_and_reflects_pending_count(node_available):
    block = _greeting_block()
    script = textwrap.dedent(f"""
        class FakeDate {{ getHours() {{ return globalThis.__fakeHour; }} }}
        globalThis.Date = FakeDate;

        {block}

        const out = {{}};
        globalThis.__fakeHour = 9;
        out.morning = _greetingLine(0);
        globalThis.__fakeHour = 14;
        out.afternoon = _greetingLine(0);
        globalThis.__fakeHour = 20;
        out.evening = _greetingLine(0);
        out.onePending = _greetingLine(1);
        out.threePending = _greetingLine(3);
        console.log(JSON.stringify(out));
    """)
    out = _run_node(script)
    assert out["morning"].startswith("Good morning."), out["morning"]
    assert out["afternoon"].startswith("Good afternoon."), out["afternoon"]
    assert out["evening"].startswith("Good evening."), out["evening"]
    assert "all clear" in out["morning"], "a zero-pending greeting should reassure, not just state a count"
    assert "One thing is waiting" in out["onePending"]
    assert "3 things are waiting" in out["threePending"]


# ===========================================================================
# #10b - the "I'm on it" empty-state data half: _agentPulseLine /
# _renderPulseLine / _loadAgentPulse
# ===========================================================================

def _agent_pulse_block() -> str:
    src = _portal_src()
    return _slice_between(src, "function _agentPulseLine() {", "function _renderEmpty(body) {")


def test_agent_pulse_line_prefers_now_then_next_then_static_fallback(node_available):
    block = _agent_pulse_block()
    script = textwrap.dedent(f"""
        let _agentPulse = null;
        let _modalEl = null;
        const ACTIVITY_API = '/api/applicant/activity';
        async function _fetchJSON() {{ throw new Error('unused in this test'); }}

        {block}

        const out = {{}};
        _agentPulse = null;
        out.noPulse = _agentPulseLine();

        _agentPulse = {{ now: {{ sentence: "Right now I'm working on your job search. I've started 3 of today's 10 applications." }} }};
        out.nowOnly = _agentPulseLine();

        _agentPulse = {{ next: {{ sentence: "Next I'll continue scanning for roles on my schedule." }} }};
        out.nextOnly = _agentPulseLine();

        _agentPulse = {{
          now: {{ sentence: "Right now I'm working on your job search." }},
          next: {{ sentence: "Next I'll continue scanning for roles on my schedule." }},
        }};
        out.bothPresentPrefersNow = _agentPulseLine();

        _agentPulse = {{ now: {{}}, next: {{}} }};
        out.emptySentencesFallsBack = _agentPulseLine();

        console.log(JSON.stringify(out));
    """)
    out = _run_node(script)
    assert out["noPulse"] == "Searching and preparing applications for you"
    assert out["nowOnly"] == "Right now I'm working on your job search. I've started 3 of today's 10 applications."
    assert out["nextOnly"] == "Next I'll continue scanning for roles on my schedule."
    assert out["bothPresentPrefersNow"] == "Right now I'm working on your job search.", (
        "when both now/next sentences are present, the concrete 'what I'm doing right "
        "now' line should win over the more generic 'what's next' line"
    )
    assert out["emptySentencesFallsBack"] == "Searching and preparing applications for you"


def test_load_agent_pulse_fetches_snapshot_and_updates_pulse_text_in_place(node_available):
    block = _agent_pulse_block()
    script = textwrap.dedent(f"""
        class FakeEl {{ constructor() {{ this.textContent = ''; }} }}
        const pulseEl = new FakeEl();
        let _agentPulse = null;
        let _modalEl = {{
          querySelector: (sel) => (sel === '#applicant-portal-pulse-text' ? pulseEl : null),
        }};
        const ACTIVITY_API = '/api/applicant/activity';
        let _fetchJSON;

        {block}

        const out = {{}};

        // Happy path: engine reachable, real activity -> pulse text updates in place.
        let requestedUrl = null;
        _fetchJSON = async (url) => {{
          requestedUrl = url;
          return {{
            engine_available: true,
            has_activity: true,
            now: {{ sentence: "Right now I'm working on your job search. I've started 2 of today's 5 applications." }},
          }};
        }};
        await _loadAgentPulse();
        out.requestedUrl = requestedUrl;
        out.textAfterSuccess = pulseEl.textContent;

        // Offline engine -> falls back to the static line, never fabricates.
        _fetchJSON = async () => ({{ engine_available: false }});
        await _loadAgentPulse();
        out.textAfterOffline = pulseEl.textContent;

        // No campaign yet -> falls back to the static line.
        _fetchJSON = async () => ({{ engine_available: true, has_activity: false }});
        await _loadAgentPulse();
        out.textAfterNoActivity = pulseEl.textContent;

        // A network failure must not throw and must fall back to the static line.
        _fetchJSON = async () => {{ throw new Error('network down'); }};
        let threw = false;
        try {{ await _loadAgentPulse(); }} catch (e) {{ threw = true; }}
        out.threwOnNetworkFailure = threw;
        out.textAfterNetworkFailure = pulseEl.textContent;

        console.log(JSON.stringify(out));
    """)
    out = _run_node(script)
    assert out["requestedUrl"] == "/api/applicant/activity/snapshot", (
        "the pulse should read the owner-scoped activity snapshot proxy, not the "
        "admin surface"
    )
    assert "I've started 2 of today's 5 applications" in out["textAfterSuccess"]
    assert out["textAfterOffline"] == "Searching and preparing applications for you"
    assert out["textAfterNoActivity"] == "Searching and preparing applications for you"
    assert out["threwOnNetworkFailure"] is False, (
        "a failed snapshot fetch is supplementary and must never throw out of _load()"
    )
    assert out["textAfterNetworkFailure"] == "Searching and preparing applications for you"


def test_empty_state_renders_pulse_text_span_wired_to_agent_pulse_line():
    src = _portal_src()
    block = _slice_between(src, "function _renderEmpty(body) {", "// ── Row rendering")
    assert 'id="applicant-portal-pulse-text"' in block, (
        "the empty state's proof-of-life line should carry a stable id so "
        "_renderPulseLine can update it in place once the snapshot loads"
    )
    assert "${esc(_agentPulseLine())}" in block, (
        "the empty state should paint with _agentPulseLine()'s current value "
        "immediately (not an empty slot waiting on a fetch)"
    )


def test_load_fires_load_agent_pulse_alongside_the_recap():
    src = _portal_src()
    block = _slice_between(src, "async function _load(showSpinner) {", "export async function openApplicantPortal()")
    assert "_loadAgentPulse();" in block, (
        "_load should fire _loadAgentPulse() on every successful pending-list load, "
        "the same fire-and-forget shape as _loadRecap()"
    )
    # It must be fired on the SAME success path as the recap, not the gated/offline/
    # error early-returns (those states don't render the empty state at all).
    recap_idx = block.index("_loadRecap();")
    pulse_idx = block.index("_loadAgentPulse();")
    assert pulse_idx > recap_idx, "expected _loadAgentPulse() to be wired next to _loadRecap()"


# ===========================================================================
# #14 - persistent "what it never does" trust contract in the Portal HEADER
# ===========================================================================

def _modal_shell_block() -> str:
    src = _portal_src()
    return _slice_between(src, "modal.innerHTML = `", "document.body.appendChild(modal);")


def test_header_carries_a_neverdoes_toggle_separate_from_the_gated_state():
    block = _modal_shell_block()
    assert 'id="applicant-portal-neverdoes"' in block, (
        "the header should carry its own 'what it never does' affordance, reachable "
        "any time the Portal is open — not only inside the gated/empty states"
    )
    assert 'id="applicant-portal-neverdoes-panel"' in block, (
        "the header toggle needs a panel host in the modal body to expand into"
    )
    assert "What it never does" in block
    # Visually quiet: a small text button next to the icon-only refresh control,
    # not styled as a primary action.
    m = re.search(r'<button[^>]*id="applicant-portal-neverdoes"[^>]*>', block)
    assert m, "could not find the header neverdoes button markup"
    btn_markup = m.group(0)
    assert "cal-btn-primary" not in btn_markup, (
        "the trust-contract toggle is a supporting signal, not a primary action"
    )


def test_header_neverdoes_button_carries_aria_expanded_and_controls():
    block = _modal_shell_block()
    m = re.search(r'<button[^>]*id="applicant-portal-neverdoes"[^>]*>', block)
    assert m, "could not find the header neverdoes button markup"
    btn_markup = m.group(0)
    assert 'aria-expanded="false"' in btn_markup, (
        "the toggle should start collapsed and expose its state to assistive tech"
    )
    assert 'aria-controls="applicant-portal-neverdoes-panel"' in btn_markup, (
        "aria-controls should point at the exact panel the toggle expands"
    )


def test_neverdoes_button_wired_to_toggle_handler():
    src = _portal_src()
    ensure_block = _slice_between(src, "function _ensureModalEl() {", "function _toggleNeverDoesPanel() {")
    assert "'#applicant-portal-neverdoes'" in ensure_block and "_toggleNeverDoesPanel" in ensure_block
    assert re.search(
        r"""querySelector\(\s*['"]#applicant-portal-neverdoes['"]\s*\)\.addEventListener\(\s*['"]click['"]\s*,\s*_toggleNeverDoesPanel\s*\)""",
        ensure_block,
    ), "the header neverdoes button should be wired to _toggleNeverDoesPanel on click"


def _toggle_never_does_panel_block() -> str:
    src = _portal_src()
    return _slice_between(src, "function _toggleNeverDoesPanel() {", "function _close() {")


def test_toggle_never_does_panel_shows_hides_and_tracks_aria_expanded(node_available):
    block = _toggle_never_does_panel_block()
    script = textwrap.dedent(f"""
        class FakeStyle {{ constructor() {{ this.display = 'none'; }} }}
        class FakeEl {{
          constructor() {{ this.style = new FakeStyle(); this.innerHTML = ''; this._attrs = {{}}; }}
          setAttribute(name, val) {{ this._attrs[name] = val; }}
          getAttribute(name) {{ return this._attrs[name]; }}
        }}
        const panel = new FakeEl();
        const btn = new FakeEl();
        let _modalEl = {{
          querySelector: (sel) => {{
            if (sel === '#applicant-portal-neverdoes-panel') return panel;
            if (sel === '#applicant-portal-neverdoes') return btn;
            return null;
          }},
        }};
        let neverDoesReturn = '<ul><li>MARKER</li></ul>';
        function _neverDoesHTML() {{ return neverDoesReturn; }}

        {block}

        const out = {{}};

        _toggleNeverDoesPanel();
        out.afterFirstDisplay = panel.style.display;
        out.afterFirstAriaExpanded = btn.getAttribute('aria-expanded');
        out.afterFirstContent = panel.innerHTML;

        _toggleNeverDoesPanel();
        out.afterSecondDisplay = panel.style.display;
        out.afterSecondAriaExpanded = btn.getAttribute('aria-expanded');
        out.afterSecondContent = panel.innerHTML;

        // Inert-when-empty: a missing trust list must not show an empty box.
        neverDoesReturn = '';
        _toggleNeverDoesPanel();
        out.inertWhenEmptyDisplay = panel.style.display;

        console.log(JSON.stringify(out));
    """)
    out = _run_node(script)
    assert out["afterFirstDisplay"] == ""
    assert out["afterFirstAriaExpanded"] == "true"
    assert "MARKER" in out["afterFirstContent"]
    assert out["afterSecondDisplay"] == "none"
    assert out["afterSecondAriaExpanded"] == "false"
    assert out["afterSecondContent"] == ""
    assert out["inertWhenEmptyDisplay"] == "none", (
        "an empty trust list should leave the panel inert rather than popping open "
        "an empty box"
    )


# ===========================================================================
# #1/#8 (Portal half) - badge refresh poll pauses while the tab is hidden
# ===========================================================================

def test_badge_poll_uses_poll_visible_not_a_raw_set_interval():
    src = _portal_src()
    boot_block = _slice_between(src, "function _boot() {", "if (document.readyState === 'loading')")
    assert re.search(r"pollVisible\(refreshBadge,\s*BADGE_POLL_MS\)", boot_block), (
        "the badge refresh poll should be wired through the shared pollVisible "
        "helper (visibilitychange-guarded), not a raw setInterval that keeps "
        "polling a hidden/backgrounded tab"
    )
    assert re.search(r"import\s*\{[^}]*\bpollVisible\b[^}]*\}\s*from\s*'\./applicantCore\.js';", src), (
        "pollVisible should be imported from the shared applicantCore helpers"
    )


def _boot_block() -> str:
    src = _portal_src()
    return _slice_between(src, "function _boot() {", "if (document.readyState === 'loading')")


def test_boot_wires_poll_visible_with_refresh_badge_and_stops_prior_handle_on_reboot(node_available):
    block = _boot_block()
    script = textwrap.dedent(f"""
        const pollVisibleCalls = [];
        let stopCallCount = 0;
        function pollVisible(fn, ms) {{
          pollVisibleCalls.push({{ fnName: fn.name, ms }});
          return function stop() {{ stopCallCount += 1; }};
        }}
        let refreshBadgeCallCount = 0;
        function refreshBadge() {{ refreshBadgeCallCount += 1; }}
        function _wireLauncher() {{}}
        function _wireKeydownActivation() {{}}
        const _LAUNCHER_IDS = [];
        const _KEYDOWN_ACTIVATE_ONLY_IDS = [];
        const BADGE_POLL_MS = 60000;
        let _badgePollStop = null;
        globalThis.document = {{ getElementById: () => null, readyState: 'complete' }};
        globalThis.setInterval = () => 1;
        globalThis.clearInterval = () => {{}};

        {block}

        const out = {{}};
        _boot();
        out.callCountAfterFirstBoot = pollVisibleCalls.length;
        out.firstMs = pollVisibleCalls[0].ms;
        out.firstFnName = pollVisibleCalls[0].fnName;
        out.stopCallsAfterFirstBoot = stopCallCount;

        _boot(); // re-booting must stop the PRIOR poll handle before starting a new one
        out.callCountAfterSecondBoot = pollVisibleCalls.length;
        out.stopCallsAfterSecondBoot = stopCallCount;
        out.refreshBadgeCallCount = refreshBadgeCallCount;

        console.log(JSON.stringify(out));
    """)
    out = _run_node(script)
    assert out["callCountAfterFirstBoot"] == 1
    assert out["firstMs"] == 60000
    assert out["firstFnName"] == "refreshBadge"
    assert out["stopCallsAfterFirstBoot"] == 0, "there is no prior poll handle to stop on the first boot"
    assert out["callCountAfterSecondBoot"] == 2
    assert out["stopCallsAfterSecondBoot"] == 1, (
        "re-booting should stop the PRIOR pollVisible handle before wiring a new one, "
        "or a re-boot would leak a second live interval"
    )
    assert out["refreshBadgeCallCount"] == 2, "each boot seeds the badge with an immediate refreshBadge() call"
