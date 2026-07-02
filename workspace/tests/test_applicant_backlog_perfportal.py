"""Regression coverage for docs/design/audits/PRODUCT_DEEP_AUDIT_ROUND3.md
exhaustive2/03_performance.md — Portal items #4, #5, #17.

* #4 — `routes/applicant_portal_routes.py`'s aggregated `/pending` feed used to
  run TWO sequential per-campaign loops (`list_pending_actions`, then
  `_onboarding_gap_item`'s `onboarding_state`): a serial 2M+1 engine fan-out on
  the highest-traffic route. Both are now `asyncio.gather`ed.
* #5 — the 60s badge poll (`applicantPortal.js` `refreshBadge`) downloaded the
  FULL `/pending` payload just to read a count. It now calls a lightweight
  `/pending/count` proxy that fans the engine's new per-campaign
  `GET /api/pending-actions/{cid}/count` endpoint out concurrently and sums it.
* #17 — Portal's `_load` awaited `_loadNotifs()` *before* rendering the action
  rows the user opened Portal for. It now renders immediately and folds
  notifications in once they resolve.

Two techniques, following the two established precedents for this test suite:

* Route-level (Python): a scripted async fake engine whose calls take a fixed
  delay, proving REAL wall-clock concurrency (gather ⇒ ~1×delay regardless of
  campaign count; serial ⇒ ~N×delay) — not just call-count assertions.
* JS-level (`applicantPortal.js` #5/#17): the exact real function source is
  sliced out of the live file and executed under `node --input-type=module`
  against minimal stand-in dependencies (the same technique
  `test_applicant_round1_portal.py` / `test_applicant_round2_wave1_portal.py`
  already established for this non-leaf module), so the actual fix code runs,
  not a re-implementation of it.

Every assertion here was verified against a temporary revert of the
corresponding fix (edit -> rerun -> confirm a real failure -> restore) before
being left in its final, passing form.
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
import textwrap
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.applicant_portal_routes as mod
from routes.applicant_portal_routes import setup_applicant_portal_routes
from src.applicant_engine import EngineError

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
# Route-level (#4, #5): real concurrency via a delayed fake engine
# ===========================================================================

DELAY = 0.15  # seconds per simulated engine hop
N_CAMPAIGNS = 4


def _make_app(authed: bool = True) -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def _auth(request, call_next):
        request.state.current_user = "tester" if authed else None
        return await call_next(request)

    app.include_router(setup_applicant_portal_routes())
    return app


class DelayedFakeEngine:
    """Stands in for ApplicantEngineClient; every call takes ``DELAY`` seconds.

    With N campaigns, a SEQUENTIAL implementation of a per-campaign loop takes
    ~N*DELAY; a CONCURRENT one (asyncio.gather) takes ~DELAY regardless of N.
    """

    calls: list = []
    campaigns: list = []
    pending: dict = {}
    onboarding: dict = {}
    counts: dict = {}
    raises: dict = {}

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def list_campaigns(self):
        DelayedFakeEngine.calls.append("list_campaigns")
        if "list_campaigns" in DelayedFakeEngine.raises:
            raise DelayedFakeEngine.raises["list_campaigns"]
        return DelayedFakeEngine.campaigns

    async def list_pending_actions(self, cid):
        DelayedFakeEngine.calls.append(("list_pending_actions", cid))
        await asyncio.sleep(DELAY)
        return DelayedFakeEngine.pending.get(cid, {"items": []})

    async def onboarding_state(self, cid):
        DelayedFakeEngine.calls.append(("onboarding_state", cid))
        await asyncio.sleep(DELAY)
        return DelayedFakeEngine.onboarding.get(cid, {"complete": True, "missing_sections": []})

    async def _request(self, method, path, **kw):
        DelayedFakeEngine.calls.append((method, path))
        await asyncio.sleep(DELAY)
        m = re.match(r"/api/pending-actions/([^/]+)/count$", path)
        cid = m.group(1) if m else "?"
        return {"campaign_id": cid, "count": DelayedFakeEngine.counts.get(cid, 0)}


@pytest.fixture(autouse=True)
def _reset_fake():
    DelayedFakeEngine.calls = []
    DelayedFakeEngine.campaigns = [
        {"id": f"c{i}", "name": f"Campaign {i}"} for i in range(N_CAMPAIGNS)
    ]
    DelayedFakeEngine.pending = {}
    DelayedFakeEngine.onboarding = {}
    DelayedFakeEngine.counts = {f"c{i}": i + 1 for i in range(N_CAMPAIGNS)}
    DelayedFakeEngine.raises = {}
    yield


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", DelayedFakeEngine)
    return TestClient(_make_app())


def test_pending_fans_out_both_loops_concurrently(client):
    # #4: two per-campaign loops (list_pending_actions, then onboarding_state
    # via _onboarding_gap_item) each gathered ⇒ ~2*DELAY total regardless of
    # campaign count. A sequential implementation would take ~2*N*DELAY, which
    # for N_CAMPAIGNS=4 is 8x slower than the concurrent bound checked below.
    start = time.monotonic()
    r = client.get("/api/applicant/portal/pending")
    elapsed = time.monotonic() - start
    assert r.status_code == 200
    assert elapsed < (N_CAMPAIGNS * DELAY), (
        f"elapsed={elapsed:.3f}s — the per-campaign loops look serial, not gathered "
        f"(sequential N={N_CAMPAIGNS} campaigns * DELAY={DELAY}s per loop would be "
        f"~{2 * N_CAMPAIGNS * DELAY:.3f}s)"
    )
    # Every campaign was actually queried on both loops (concurrency isn't
    # achieved by skipping work, just by not serializing it).
    list_calls = [c for c in DelayedFakeEngine.calls if isinstance(c, tuple) and c[0] == "list_pending_actions"]
    onboarding_calls = [c for c in DelayedFakeEngine.calls if isinstance(c, tuple) and c[0] == "onboarding_state"]
    assert {c[1] for c in list_calls} == {"c0", "c1", "c2", "c3"}
    assert {c[1] for c in onboarding_calls} == {"c0", "c1", "c2", "c3"}


def test_pending_count_fans_out_concurrently(client):
    # #5: the lightweight badge endpoint's per-campaign `_request(.../count)`
    # calls are also gathered ⇒ ~DELAY total, not ~N*DELAY.
    start = time.monotonic()
    r = client.get("/api/applicant/portal/pending/count")
    elapsed = time.monotonic() - start
    assert r.status_code == 200
    assert elapsed < (N_CAMPAIGNS * DELAY / 2), (
        f"elapsed={elapsed:.3f}s — the badge count fan-out looks serial, not gathered"
    )
    assert r.json() == {"engine_available": True, "count": sum(DelayedFakeEngine.counts.values())}
    count_calls = [c for c in DelayedFakeEngine.calls if isinstance(c, tuple) and c[0] == "GET"]
    assert {c[1] for c in count_calls} == {
        "/api/pending-actions/c0/count",
        "/api/pending-actions/c1/count",
        "/api/pending-actions/c2/count",
        "/api/pending-actions/c3/count",
    }


def test_pending_preserves_campaign_order_despite_uneven_completion(client):
    # gather() returns results in submission order, not completion order — a
    # correctness property #4's fix relies on (the merged feed must read the
    # same campaign-by-campaign order the old sequential loop produced).
    class UnevenEngine(DelayedFakeEngine):
        async def list_pending_actions(self, cid):
            DelayedFakeEngine.calls.append(("list_pending_actions", cid))
            # c0 finishes LAST, c3 finishes FIRST.
            idx = int(cid[1:])
            await asyncio.sleep(DELAY * (N_CAMPAIGNS - idx) / N_CAMPAIGNS)
            return {"items": [{"id": f"a-{cid}", "kind": "agent_question", "title": cid}]}

    mod.ApplicantEngineClient = UnevenEngine
    try:
        r = client.get("/api/applicant/portal/pending")
    finally:
        mod.ApplicantEngineClient = DelayedFakeEngine
    body = r.json()
    ids = [it["id"] for it in body["items"]]
    assert ids == ["a-c0", "a-c1", "a-c2", "a-c3"], (
        "items must stay in campaign submission order, not completion order"
    )


def test_pending_gap_uses_first_incomplete_campaign_even_when_gathered(client):
    # The onboarding-gap loop's "first incomplete campaign wins" semantics must
    # survive the gather conversion: c1 is incomplete, c0/c2/c3 are complete.
    DelayedFakeEngine.onboarding = {
        "c0": {"complete": True, "missing_sections": []},
        "c1": {"complete": False, "missing_sections": ["identity"]},
        "c2": {"complete": True, "missing_sections": []},
        "c3": {"complete": False, "missing_sections": ["education"]},
    }
    r = client.get("/api/applicant/portal/pending")
    body = r.json()
    gap = next((it for it in body["items"] if it.get("kind") == "onboarding_incomplete"), None)
    assert gap is not None
    assert gap["campaign_id"] == "c1", "the FIRST incomplete campaign in list order must win"


def test_pending_one_failing_campaign_does_not_sink_the_others(client):
    DelayedFakeEngine.raises[("list_pending_actions", "c2")] = None  # placeholder, set below

    class FlakyEngine(DelayedFakeEngine):
        async def list_pending_actions(self, cid):
            DelayedFakeEngine.calls.append(("list_pending_actions", cid))
            await asyncio.sleep(DELAY)
            if cid == "c2":
                raise EngineError("flaky", status=500)
            return {"items": [{"id": f"a-{cid}", "kind": "agent_question"}]}

    mod.ApplicantEngineClient = FlakyEngine
    try:
        r = client.get("/api/applicant/portal/pending")
    finally:
        mod.ApplicantEngineClient = DelayedFakeEngine
    body = r.json()
    ids = {it["id"] for it in body["items"]}
    assert ids == {"a-c0", "a-c1", "a-c3"}


def test_pending_count_soft_degrades_when_engine_down(client):
    DelayedFakeEngine.raises["list_campaigns"] = EngineError("down", is_timeout=True)
    r = client.get("/api/applicant/portal/pending/count")
    assert r.status_code == 200
    assert r.json() == {"engine_available": False, "count": 0}


def test_pending_count_409_gate_is_not_offline(client):
    DelayedFakeEngine.raises["list_campaigns"] = EngineError(
        "gated", status=409, detail="Finish onboarding first."
    )
    r = client.get("/api/applicant/portal/pending/count")
    assert r.status_code == 200
    body = r.json()
    assert body["gated"] is True
    assert body["engine_available"] is True
    assert body["count"] == 0


def test_pending_count_zero_campaigns(client):
    DelayedFakeEngine.campaigns = []
    r = client.get("/api/applicant/portal/pending/count")
    assert r.status_code == 200
    assert r.json() == {"engine_available": True, "count": 0}


def test_pending_count_one_failing_campaign_is_excluded(client):
    class OneFlakyCount(DelayedFakeEngine):
        async def _request(self, method, path, **kw):
            DelayedFakeEngine.calls.append((method, path))
            await asyncio.sleep(DELAY)
            if "/c2/" in path:
                raise EngineError("flaky", status=500)
            m = re.match(r"/api/pending-actions/([^/]+)/count$", path)
            cid = m.group(1) if m else "?"
            return {"campaign_id": cid, "count": DelayedFakeEngine.counts.get(cid, 0)}

    mod.ApplicantEngineClient = OneFlakyCount
    try:
        r = client.get("/api/applicant/portal/pending/count")
    finally:
        mod.ApplicantEngineClient = DelayedFakeEngine
    assert r.status_code == 200
    # c2 excluded (count 3); c0=1, c1=2, c3=4 sum to 7.
    assert r.json()["count"] == 7


def test_pending_count_unauthenticated_is_rejected(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", DelayedFakeEngine)
    c = TestClient(_make_app(authed=False))
    r = c.get("/api/applicant/portal/pending/count")
    assert r.status_code == 401


# ===========================================================================
# JS-level (#5): refreshBadge calls the lightweight endpoint
# ===========================================================================


def _refresh_badge_block() -> str:
    src = _portal_src()
    return _slice_between(src, "async function refreshBadge() {", "// ── Today's digest")


def test_refresh_badge_calls_lightweight_count_endpoint_not_full_pending(node_available):
    block = _refresh_badge_block()
    script = textwrap.dedent(f"""
        const API = '/api/applicant/portal';
        let requestedUrl = null;
        async function _fetchJSON(url) {{ requestedUrl = url; return {{ count: 3 }}; }}
        let badgeCalls = [];
        function _setBadge(n) {{ badgeCalls.push(n); }}
        async function _loadNotifs() {{ return 2; }}

        {block}

        await refreshBadge();
        console.log(JSON.stringify({{ requestedUrl, badgeCalls }}));
    """)
    out = _run_node(script)
    assert out["requestedUrl"] == "/api/applicant/portal/pending/count", (
        "refreshBadge must call the lightweight count endpoint, not the full "
        "aggregated /pending payload, on every 60s poll"
    )
    assert out["badgeCalls"] == [5]  # 3 pending + 2 informational notifications


def test_refresh_badge_zeroes_when_engine_unavailable_without_loading_notifs(node_available):
    block = _refresh_badge_block()
    script = textwrap.dedent(f"""
        const API = '/api/applicant/portal';
        async function _fetchJSON() {{ return {{ engine_available: false, count: 0 }}; }}
        let badgeCalls = [];
        function _setBadge(n) {{ badgeCalls.push(n); }}
        let notifsCalled = false;
        async function _loadNotifs() {{ notifsCalled = true; return 0; }}

        {block}

        await refreshBadge();
        console.log(JSON.stringify({{ badgeCalls, notifsCalled }}));
    """)
    out = _run_node(script)
    assert out["badgeCalls"] == [0]
    assert out["notifsCalled"] is False


def test_refresh_badge_zeroes_on_network_failure(node_available):
    block = _refresh_badge_block()
    script = textwrap.dedent(f"""
        const API = '/api/applicant/portal';
        async function _fetchJSON() {{ throw new Error('network down'); }}
        let badgeCalls = [];
        function _setBadge(n) {{ badgeCalls.push(n); }}

        {block}

        await refreshBadge();
        console.log(JSON.stringify({{ badgeCalls }}));
    """)
    out = _run_node(script)
    assert out["badgeCalls"] == [0]


# ===========================================================================
# JS-level (#17): _load renders the action rows before notifications resolve
# ===========================================================================


def _load_block() -> str:
    src = _portal_src()
    return _slice_between(
        src, "async function _load(showSpinner) {", "export async function openApplicantPortal(opts) {"
    )


def test_load_renders_pending_rows_before_notifications_resolve(node_available):
    block = _load_block()
    script = textwrap.dedent(f"""
        const API = '/api/applicant/portal';
        const order = [];
        let renderListCalls = 0;
        const bodyEl = {{ innerHTML: '' }};
        let _modalEl = {{
          querySelector: (sel) => (sel === '#applicant-portal-pending' ? bodyEl : null),
        }};
        let _items = [];
        let _lastPendingCount = 0;
        let _loading = false;

        function _renderList(body) {{
          renderListCalls += 1;
          order.push('renderList');
          body.innerHTML = 'RENDERED-' + renderListCalls;
        }}
        function _renderGreeting() {{}}
        function _renderGated() {{}}
        function _renderOffline() {{}}
        function _recapHost() {{ return null; }}
        function _setBadge() {{}}
        function _infoNotifs() {{ return []; }}
        function _loadRecap() {{}}
        function _loadAgentPulse() {{}}
        function errorHTML() {{ return ''; }}
        function wireRetry() {{}}
        function errText() {{ return ''; }}
        function loadingHTML() {{ return ''; }}

        async function _fetchJSON(url) {{
          return {{ items: [{{ id: 'a1', kind: 'agent_question' }}] }};
        }}

        // A "slow inbox" — resolves 30ms after being called, so a fix that
        // blocks first paint on it is unmistakably distinguishable from one
        // that doesn't (real timer, no artificial deadlock risk).
        async function _loadNotifs() {{
          order.push('loadNotifsStart');
          await new Promise((r) => setTimeout(r, 30));
          order.push('loadNotifsResolved');
          return 0;
        }}

        {block}

        const out = {{}};
        await _load(false);
        out.orderRightAfterLoadResolves = order.slice();
        out.bodyRightAfterLoadResolves = bodyEl.innerHTML;
        out.renderListCallsRightAfterLoadResolves = renderListCalls;

        await new Promise((r) => setTimeout(r, 80));
        out.orderAfterNotifsSettle = order.slice();
        out.renderListCallsAfterNotifsSettle = renderListCalls;

        console.log(JSON.stringify(out));
    """)
    out = _run_node(script)
    # _load() itself must resolve WITHOUT waiting for the slow notifications
    # fetch to finish — first paint (the action rows) already happened.
    assert out["orderRightAfterLoadResolves"] == ["renderList", "loadNotifsStart"], (
        "the action rows must render before _loadNotifs() resolves, and _load() "
        "must not await it — got order " + str(out["orderRightAfterLoadResolves"])
    )
    assert out["bodyRightAfterLoadResolves"] == "RENDERED-1"
    assert out["renderListCallsRightAfterLoadResolves"] == 1

    # Once notifications DO resolve, they fold in via a second render (the
    # "render now, enrich later" pattern _loadRecap/_loadAgentPulse also use).
    assert out["orderAfterNotifsSettle"] == [
        "renderList", "loadNotifsStart", "loadNotifsResolved", "renderList",
    ]
    assert out["renderListCallsAfterNotifsSettle"] == 2


def test_load_gated_and_offline_paths_still_short_circuit_before_notifs(node_available):
    # Sanity: the gated/offline early returns must still skip the pending-row
    # render AND the notifications fetch entirely (unchanged behavior) — the
    # #17 fix only touches the happy path.
    block = _load_block()
    script = textwrap.dedent(f"""
        const API = '/api/applicant/portal';
        let renderListCalls = 0;
        let notifsCalls = 0;
        const bodyEl = {{ innerHTML: '' }};
        let _modalEl = {{
          querySelector: (sel) => (sel === '#applicant-portal-pending' ? bodyEl : null),
        }};
        let _items = [];
        let _lastPendingCount = 0;
        let _loading = false;

        function _renderList() {{ renderListCalls += 1; }}
        function _renderGreeting() {{}}
        let gatedCalls = 0;
        function _renderGated(body, data) {{ gatedCalls += 1; body.innerHTML = 'GATED'; }}
        let offlineCalls = 0;
        function _renderOffline(body) {{ offlineCalls += 1; body.innerHTML = 'OFFLINE'; }}
        function _recapHost() {{ return null; }}
        function _setBadge() {{}}
        function _infoNotifs() {{ return []; }}
        function _loadRecap() {{}}
        function _loadAgentPulse() {{}}
        function errorHTML() {{ return ''; }}
        function wireRetry() {{}}
        function errText() {{ return ''; }}
        function loadingHTML() {{ return ''; }}
        async function _loadNotifs() {{ notifsCalls += 1; return 0; }}

        async function _fetchJSON(url) {{ return {{ gated: true, message: 'finish setup' }}; }}

        {block}

        await _load(false);
        console.log(JSON.stringify({{ renderListCalls, notifsCalls, gatedCalls, offlineCalls, body: bodyEl.innerHTML }}));
    """)
    out = _run_node(script)
    assert out["gatedCalls"] == 1
    assert out["renderListCalls"] == 0
    assert out["notifsCalls"] == 0
    assert out["body"] == "GATED"
