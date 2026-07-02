"""Regression coverage for docs/design/audits/PRODUCT_EXHAUSTIVE_AUDIT.md §4B's
"daily ritual" backlog item, confined to workspace/static/js/applicantPortal.js:

  1. Milestone celebrations — a ONE-TIME toast when a round-number
     "applications sent" threshold (10/25/50/100) is crossed, sourced from the
     SAME funnel data `_loadMomentum` already fetches (`summary.total_submitted`
     off `/api/applicant/results`), reusing the exact `_toast` mechanism the
     outcome-loop's own celebratory notifications already surface through
     (rather than a second celebration mechanism). Deduped in localStorage
     (`applicant_portal_milestones_shown`, mirroring the `applicant_vault_*`
     key-naming convention).
  2. Supportive streak — "days in a row the agent has been actively working",
     computed from the SAME run-history proxy `_loadRecap` reads
     (`/api/applicant/activity/runs`), grouped into calendar days and counted
     backward from today with one day's grace. Deliberately not punitive: no
     broken-streak callout, no red/warning styling — it just quietly stops
     rendering below a 2-day streak.
  3. "Today at a glance" — a compact one-line summary of TODAY specifically,
     reusing the exact `_agentPulse` snapshot data `_agentPulseLine` already
     reads (`/api/applicant/activity/snapshot`'s `now`/`next` blocks) — no new
     data path.

Every fact below is read from the ACTUAL current source of applicantPortal.js
(no duplicated re-implementation of the logic under test), following the
exact precedent workspace/tests/test_applicant_round2_wave1_portal.py already
established for this file:

  * plain Python regex-over-source-text for markup/wiring facts, and
  * extracting a REAL private function's source text out of the live file at
    test time and running it under `node --input-type=module` against a
    minimal fake `document`/`window`/`fetch`, so the pure logic under test is
    genuinely executed, not just pattern-matched.

Every assertion here was verified against a temporary revert of the
corresponding fix (edit -> rerun -> confirm a real AssertionError -> restore)
before being left in its final, passing form.
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


def _fake_local_storage_js() -> str:
    """A minimal in-memory localStorage, mirroring the fake already used by
    test_applicant_round2_wave3_hashrouting.py for this same file."""
    return (
        "globalThis.localStorage = { _s:{}, "
        "getItem(k){ return Object.prototype.hasOwnProperty.call(this._s,k)?this._s[k]:null; }, "
        "setItem(k,v){ this._s[k]=String(v); }, "
        "removeItem(k){ delete this._s[k]; } }; "
        "globalThis.window = { localStorage: globalThis.localStorage };"
    )


# ===========================================================================
# Modal template carries the two new slots the milestone/streak/today-glance
# renderers target.
# ===========================================================================

def _modal_shell_block() -> str:
    src = _portal_src()
    return _slice_between(src, "modal.innerHTML = `", "document.body.appendChild(modal);")


def test_modal_shell_carries_today_and_streak_slots():
    block = _modal_shell_block()
    assert 'id="applicant-portal-today"' in block, (
        "the modal body needs a dedicated 'today at a glance' host, always "
        "visible (not nested inside the empty state)"
    )
    assert 'id="applicant-portal-streak"' in block, (
        "the modal body needs a dedicated supportive-streak host"
    )
    # Both new slots must sit ahead of the pending list itself.
    today_idx = block.index('id="applicant-portal-today"')
    streak_idx = block.index('id="applicant-portal-streak"')
    pending_idx = block.index('id="applicant-portal-pending"')
    assert today_idx < pending_idx and streak_idx < pending_idx


# ===========================================================================
# 1. Milestone celebrations
# ===========================================================================

def _milestones_block() -> str:
    src = _portal_src()
    return _slice_between(src, "const SUBMIT_MILESTONES = [10, 25, 50, 100];", "// ── Empty / offline states")


def test_submit_milestone_dedup_key_mirrors_vault_naming_convention():
    src = _portal_src()
    assert "const MILESTONES_SEEN_KEY = 'applicant_portal_milestones_shown';" in src, (
        "the milestone-dedup localStorage key should follow the "
        "`applicant_<surface>_<purpose>` naming applicantVault.js's "
        "LAST_CAMPAIGN_KEY ('applicant_vault_last_campaign_id') established"
    )


def test_check_submit_milestone_toasts_once_on_first_crossing(node_available):
    block = _milestones_block()
    script = textwrap.dedent(f"""
        {_fake_local_storage_js()}
        const MILESTONES_SEEN_KEY = 'applicant_portal_milestones_shown';
        const toasts = [];
        function _toast(msg) {{ toasts.push(msg); }}

        {block}

        const out = {{}};
        _checkSubmitMilestone({{ total_submitted: 10 }});
        out.toastsAfterFirstCross = toasts.slice();

        // Re-checking the SAME count again must not re-toast (one-time).
        _checkSubmitMilestone({{ total_submitted: 10 }});
        out.toastsAfterRecheck = toasts.slice();

        console.log(JSON.stringify(out));
    """)
    out = _run_node(script)
    assert len(out["toastsAfterFirstCross"]) == 1
    assert "10" in out["toastsAfterFirstCross"][0]
    assert "applications sent" in out["toastsAfterFirstCross"][0]
    assert out["toastsAfterRecheck"] == out["toastsAfterFirstCross"], (
        "the milestone must never re-announce once already seen (localStorage dedup)"
    )


def test_check_submit_milestone_big_jump_celebrates_only_the_highest(node_available):
    """A batch of submissions landing between two Portal visits can jump past
    several thresholds at once (e.g. 5 -> 30). Only the highest newly-crossed
    threshold should be announced, and the smaller ones must be marked seen
    too so they never fire retroactively on a later, smaller check."""
    block = _milestones_block()
    script = textwrap.dedent(f"""
        {_fake_local_storage_js()}
        const MILESTONES_SEEN_KEY = 'applicant_portal_milestones_shown';
        const toasts = [];
        function _toast(msg) {{ toasts.push(msg); }}

        {block}

        const out = {{}};
        _checkSubmitMilestone({{ total_submitted: 30 }});
        out.toastsAfterJump = toasts.slice();

        // A later visit with a HIGHER count than any prior toast must still
        // reach the next unseen threshold (100).
        _checkSubmitMilestone({{ total_submitted: 120 }});
        out.toastsAfterFurtherGrowth = toasts.slice();

        console.log(JSON.stringify(out));
    """)
    out = _run_node(script)
    assert len(out["toastsAfterJump"]) == 1
    assert "25" in out["toastsAfterJump"][0], (
        f"expected the highest crossed threshold (25) to be the one celebrated, got {out['toastsAfterJump']}"
    )
    assert len(out["toastsAfterFurtherGrowth"]) == 2
    assert "100" in out["toastsAfterFurtherGrowth"][1]


def test_check_submit_milestone_no_op_below_first_threshold(node_available):
    block = _milestones_block()
    script = textwrap.dedent(f"""
        {_fake_local_storage_js()}
        const MILESTONES_SEEN_KEY = 'applicant_portal_milestones_shown';
        const toasts = [];
        function _toast(msg) {{ toasts.push(msg); }}

        {block}

        const out = {{}};
        _checkSubmitMilestone({{ total_submitted: 9 }});
        out.toastsBelowThreshold = toasts.slice();
        _checkSubmitMilestone({{}});
        out.toastsWithNoSummary = toasts.slice();

        console.log(JSON.stringify(out));
    """)
    out = _run_node(script)
    assert out["toastsBelowThreshold"] == []
    assert out["toastsWithNoSummary"] == []


def test_load_momentum_wires_the_milestone_check_to_the_same_summary():
    src = _portal_src()
    block = _slice_between(src, "async function _loadMomentum() {", "// ── Milestone celebrations")
    assert "_checkSubmitMilestone(data.summary);" in block, (
        "_loadMomentum should feed the milestone check the SAME summary object "
        "it just rendered — no second fetch/data path"
    )
    # It must fire on the SAME success path as the render, after has_data/gated/
    # offline have already been ruled out.
    render_idx = block.index("_renderMomentum(host, data);")
    check_idx = block.index("_checkSubmitMilestone(data.summary);")
    assert check_idx > render_idx


def test_milestones_do_not_duplicate_the_first_interview_celebration():
    """The engine's own notify_positive_outcome() already fires a celebratory
    in-app notification on every interview invite, which Portal already toasts
    on arrival via _toastNew. A second, Portal-local 'first interview' trigger
    would double-announce the exact same event — guard that no such client-side
    interview-milestone trigger was added."""
    src = _portal_src()
    block = _milestones_block()
    assert "interview" not in block.lower(), (
        "milestone celebrations should not compute a client-side 'first "
        "interview' trigger — that would duplicate the engine's own "
        "notify_positive_outcome() celebration, already surfaced via the "
        "existing notification-toast pipeline (_toastNew)"
    )
    assert "signals" not in src or "signals" not in block


# ===========================================================================
# 2. Supportive streak
# ===========================================================================

def _streak_block() -> str:
    src = _portal_src()
    return _slice_between(src, "const _ONE_DAY_MS", "// ── Momentum strip")


def _run_ts_block() -> str:
    """`_runTs` lives earlier in the file (shared with `_loadRecap`) — the
    streak logic calls it by name, so tests exercising `_computeStreakDays`/
    `_loadStreak` need the REAL implementation in scope too."""
    src = _portal_src()
    return _slice_between(src, "function _runTs(run) {", "function _recapTotals(items, since) {")


def test_compute_streak_days_counts_consecutive_days_ending_today(node_available):
    block = _streak_block()
    script = textwrap.dedent(f"""
        let _modalEl = null;
        {_run_ts_block()}
        {block}

        const out = {{}};
        const now = Date.now();
        const day = 24 * 60 * 60 * 1000;
        const mk = (offsetDays) => ({{ created_at: new Date(now - offsetDays * day).toISOString() }});

        // Runs today, yesterday, and the day before -> a 3-day streak.
        out.threeDayStreak = _computeStreakDays([mk(0), mk(1), mk(2)]);

        // A single run today only -> not yet a "streak" (still >= 1).
        out.oneDay = _computeStreakDays([mk(0)]);

        // No runs at all -> 0.
        out.noRuns = _computeStreakDays([]);

        console.log(JSON.stringify(out));
    """)
    out = _run_node(script)
    assert out["threeDayStreak"] == 3
    assert out["oneDay"] == 1
    assert out["noRuns"] == 0


def test_compute_streak_days_grace_when_today_has_not_ticked_yet(node_available):
    """No run yet TODAY (the scheduler simply hasn't ticked yet) should not
    read as a broken streak if yesterday (and the day before) had runs."""
    block = _streak_block()
    script = textwrap.dedent(f"""
        let _modalEl = null;
        {_run_ts_block()}
        {block}

        const out = {{}};
        const now = Date.now();
        const day = 24 * 60 * 60 * 1000;
        const mk = (offsetDays) => ({{ created_at: new Date(now - offsetDays * day).toISOString() }});

        // Runs yesterday and the day before, nothing yet today.
        out.graceStreak = _computeStreakDays([mk(1), mk(2)]);

        console.log(JSON.stringify(out));
    """)
    out = _run_node(script)
    assert out["graceStreak"] == 2, (
        "a run yesterday (but not yet today) should still anchor a streak via "
        "the one-day grace, not read as broken"
    )


def test_compute_streak_days_resets_quietly_on_a_real_gap(node_available):
    block = _streak_block()
    script = textwrap.dedent(f"""
        let _modalEl = null;
        {_run_ts_block()}
        {block}

        const out = {{}};
        const now = Date.now();
        const day = 24 * 60 * 60 * 1000;
        const mk = (offsetDays) => ({{ created_at: new Date(now - offsetDays * day).toISOString() }});

        // A real gap: nothing today or yesterday, only 3 days ago.
        out.gapReset = _computeStreakDays([mk(3), mk(4)]);

        console.log(JSON.stringify(out));
    """)
    out = _run_node(script)
    assert out["gapReset"] == 0


def test_render_streak_is_not_punitive_no_warning_styling_and_hides_below_two_days():
    src = _portal_src()
    block = _slice_between(src, "function _renderStreak(host, days) {", "async function _loadStreak() {")
    assert "color-danger" not in block and "color-warning" not in block and "red" not in block.lower(), (
        "the streak line must never use warning/danger styling — no "
        "broken-streak shaming, per the daily-ritual spec"
    )
    assert "days >= 2" in block or "days>=2" in block.replace(" ", ""), (
        "a 1-day (or 0-day) streak should not render as a streak yet"
    )


def test_render_streak_hides_or_shows_correctly(node_available):
    src = _portal_src()
    block = _slice_between(src, "function _renderStreak(host, days) {", "async function _loadStreak() {")
    script = textwrap.dedent(f"""
        class FakeEl {{ constructor() {{ this.innerHTML = '__unset__'; }} }}

        {block}

        const out = {{}};
        let host = new FakeEl();
        _renderStreak(host, 0);
        out.zeroDaysHidden = host.innerHTML === '';

        host = new FakeEl();
        _renderStreak(host, 1);
        out.oneDayHidden = host.innerHTML === '';

        host = new FakeEl();
        _renderStreak(host, 5);
        out.fiveDaysShown = host.innerHTML.includes('5') && host.innerHTML.includes('days running');

        console.log(JSON.stringify(out));
    """)
    out = _run_node(script)
    assert out["zeroDaysHidden"] is True
    assert out["oneDayHidden"] is True
    assert out["fiveDaysShown"] is True


def test_load_streak_reuses_the_activity_runs_endpoint_and_degrades_soft(node_available):
    block = _streak_block()
    script = textwrap.dedent(f"""
        class FakeEl {{ constructor() {{ this.innerHTML = '__unset__'; }} }}
        const streakEl = new FakeEl();
        let _modalEl = {{
          querySelector: (sel) => (sel === '#applicant-portal-streak' ? streakEl : null),
        }};
        const ACTIVITY_API = '/api/applicant/activity';
        let _fetchJSON;

        {_run_ts_block()}
        {block}

        const out = {{}};
        let requestedUrl = null;
        _fetchJSON = async (url) => {{
          requestedUrl = url;
          return {{
            engine_available: true,
            items: [
              {{ created_at: new Date().toISOString() }},
              {{ created_at: new Date(Date.now() - 86400000).toISOString() }},
              {{ created_at: new Date(Date.now() - 2 * 86400000).toISOString() }},
            ],
          }};
        }};
        await _loadStreak();
        out.requestedUrl = requestedUrl;
        out.textAfterSuccess = streakEl.innerHTML;

        _fetchJSON = async () => ({{ engine_available: false }});
        await _loadStreak();
        out.textAfterOffline = streakEl.innerHTML;

        _fetchJSON = async () => ({{ engine_available: true, gated: true }});
        await _loadStreak();
        out.textAfterGated = streakEl.innerHTML;

        _fetchJSON = async () => {{ throw new Error('network down'); }};
        let threw = false;
        try {{ await _loadStreak(); }} catch (e) {{ threw = true; }}
        out.threwOnNetworkFailure = threw;

        console.log(JSON.stringify(out));
    """)
    out = _run_node(script)
    assert out["requestedUrl"] == "/api/applicant/activity/runs", (
        "the streak should reuse the SAME run-history endpoint _loadRecap reads, "
        "not a new one"
    )
    assert "3 days running" in out["textAfterSuccess"]
    assert out["textAfterOffline"] == ""
    assert out["textAfterGated"] == ""
    assert out["threwOnNetworkFailure"] is False


def test_streak_wired_into_open_and_refresh():
    src = _portal_src()
    open_block = _slice_between(src, "export async function openApplicantPortal(opts)", "\n}\n")
    assert "_loadStreak();" in open_block, (
        "openApplicantPortal should kick off the streak load, mirroring "
        "_loadMomentum()"
    )
    m = re.search(
        r"""querySelector\(\s*['"]#applicant-portal-refresh['"]\s*\)\.addEventListener\(\s*['"]click['"]\s*,\s*\(\)\s*=>\s*\{([^}]*)\}\s*\)""",
        src,
    )
    assert m, "could not find the refresh button's click handler"
    assert "_loadStreak();" in m.group(1), (
        "the refresh button should also re-fire the streak load, matching the "
        "recap/momentum/digest refresh pattern"
    )


# ===========================================================================
# 3. "Today at a glance"
# ===========================================================================

def _today_glance_block() -> str:
    src = _portal_src()
    return _slice_between(src, "function _todayHost() {", "async function _loadAgentPulse() {")


def test_today_glance_line_reuses_agent_pulse_data(node_available):
    block = _today_glance_block()
    script = textwrap.dedent(f"""
        let _agentPulse = null;
        let _modalEl = null;
        function esc(s) {{ return String(s); }}

        {block}

        const out = {{}};
        out.noPulse = _todayGlanceLine();

        _agentPulse = {{ now: {{ applied_today: 3, daily_budget: 10 }} }};
        out.appliedAndBudget = _todayGlanceLine();

        _agentPulse = {{ now: {{ applied_today: 2 }} }};
        out.appliedOnly = _todayGlanceLine();

        _agentPulse = {{ now: {{ applied_today: 3, daily_budget: 10 }}, next: {{ pending_actions: 2 }} }};
        out.appliedBudgetAndPending = _todayGlanceLine();

        _agentPulse = {{ now: {{}}, next: {{}} }};
        out.nothingConcrete = _todayGlanceLine();

        console.log(JSON.stringify(out));
    """)
    out = _run_node(script)
    assert out["noPulse"] == ""
    assert out["appliedAndBudget"] == "Today: 3 of 10 applications started"
    assert out["appliedOnly"] == "Today: 2 applications started today"
    assert out["appliedBudgetAndPending"] == "Today: 3 of 10 applications started · 2 need you"
    assert out["nothingConcrete"] == "", (
        "with no concrete today-numbers from the engine, the glance line must "
        "stay empty rather than fabricate one"
    )


def test_render_today_glance_updates_host_in_place(node_available):
    block = _today_glance_block()
    script = textwrap.dedent(f"""
        class FakeEl {{ constructor() {{ this.innerHTML = '__unset__'; }} }}
        const todayEl = new FakeEl();
        let _agentPulse = {{ now: {{ applied_today: 4, daily_budget: 8 }} }};
        let _modalEl = {{
          querySelector: (sel) => (sel === '#applicant-portal-today' ? todayEl : null),
        }};
        function esc(s) {{ return String(s); }}

        {block}

        const out = {{}};
        _renderTodayGlance();
        out.textWithData = todayEl.innerHTML;

        _agentPulse = null;
        _renderTodayGlance();
        out.textWithoutData = todayEl.innerHTML;

        // A missing host must not throw.
        _modalEl = {{ querySelector: () => null }};
        let threw = false;
        try {{ _renderTodayGlance(); }} catch (e) {{ threw = true; }}
        out.missingHostThrew = threw;

        console.log(JSON.stringify(out));
    """)
    out = _run_node(script)
    assert "4 of 8 applications started" in out["textWithData"]
    assert out["textWithoutData"] == ""
    assert out["missingHostThrew"] is False


def test_load_agent_pulse_also_renders_today_glance_defensively():
    src = _portal_src()
    block = _slice_between(src, "async function _loadAgentPulse() {", "function _renderEmpty(body) {")
    assert "_renderTodayGlance();" in block, (
        "_loadAgentPulse should also update the today-at-a-glance line from the "
        "SAME snapshot fetch, not a separate data path"
    )
    assert re.search(r"try\s*\{\s*_renderTodayGlance\(\);\s*\}\s*catch", block), (
        "the today-glance render must be defensive (try/catch) so a missing "
        "host or unexpected shape never breaks the pulse-line update alongside it"
    )
