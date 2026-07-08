"""P1-12 — narrative FE homes for engine capabilities (road-to-market backlog).

Pins the three surfacing seams this story adds, each reusing an EXISTING
proxy/read-model (no new engine logic):

1. **Tracker** — the daily post-submission sweep's ghosting flags + drafted
   (never auto-sent) follow-ups render per-application on the Tracker through
   the existing ``/api/applicant/followups`` proxy, with an editable
   review-then-approve affordance for each draft (source-composition pins over
   ``applicantTracker.js``).
2. **Activity** — the learning/outcomes loop (``LearningService.build_summary``,
   previously admin-Debug-only) gets an owner-scoped read at
   ``GET /api/applicant/activity/learning`` and a "What I'm learning" section
   at the foot of the Activity page (route tests over a scripted FakeEngine +
   source pins, plus the pure ``_learningLines`` builder run headlessly under
   node).
3. **Daily updates** — the weekly recap (already pushed once a week through the
   notification fan-out) becomes readable on demand at
   ``GET /api/applicant/email/digest/{id}/weekly-recap`` and renders as a
   "Your week so far" line in the Daily-updates panel (mock-transport relay
   tests + source pins).

Harness patterns mirror ``test_applicant_activity_routes.py`` (FakeEngine),
``test_applicant_email_routes.py`` (httpx.MockTransport through the module's
``_engine_client`` seam), and ``test_applicant_health_panel_js.py``
(source-composition regex + node slice-execution).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import routes.applicant_activity_routes as activity_mod
import routes.applicant_email_routes as email_mod
from routes.applicant_activity_routes import setup_applicant_activity_routes
from routes.applicant_email_routes import setup_applicant_email_routes
from src.applicant_engine import ApplicantEngineClient, EngineError

_REPO = Path(__file__).resolve().parent.parent  # workspace/
_JS = _REPO / "static" / "js"
_TRACKER_JS = (_JS / "applicantTracker.js").read_text(encoding="utf-8")
_ACTIVITY_JS = (_JS / "applicantActivity.js").read_text(encoding="utf-8")
_DIGEST_JS = (_JS / "emailLibrary" / "applicantDigest.js").read_text(encoding="utf-8")
_HAS_NODE = shutil.which("node") is not None


# ── 1. Tracker: ghosted + drafted follow-ups (source composition) ────────────


def test_tracker_reads_the_followups_proxy():
    # The panel reads the EXISTING owner-scoped attention proxy, never the
    # engine directly, and never a second bespoke endpoint.
    assert "const FOLLOWUPS_API = '/api/applicant/followups'" in _TRACKER_JS
    assert "_fetchJSON(`${FOLLOWUPS_API}/${encodeURIComponent(cid)}`)" in _TRACKER_JS


def test_tracker_has_the_attention_panel_and_reloads_it_with_the_board():
    assert 'id="applicant-tracker-attention"' in _TRACKER_JS
    # The panel keys off the board's own campaign ids, so it (re)loads whenever
    # the board itself does — one wiring point inside _load.
    assert "_loadAttention();" in _TRACKER_JS
    assert "function _attentionCampaignIds()" in _TRACKER_JS


def test_tracker_followup_draft_is_reviewable_and_editable_before_approving():
    # The full drafted subject/body render as editable fields inside a
    # collapsed-by-default disclosure — review-before-send, never blind-approve.
    assert 'data-followup-subject="${id}"' in _TRACKER_JS
    assert 'data-followup-body="${id}"' in _TRACKER_JS
    assert "Review &amp; send" in _TRACKER_JS


def test_tracker_approve_posts_through_the_owner_approval_only_proxy_path():
    # Approving posts to the SAME proxy route that is the product's only lane
    # onto PostSubmissionService.schedule_follow_up (never a new engine seam).
    assert (
        "_post(`${FOLLOWUPS_API}/applications/${encodeURIComponent(id)}/approve`" in _TRACKER_JS
    )
    assert "data-followup-approve" in _TRACKER_JS


def test_tracker_ghost_rows_are_informational_and_honest():
    # A ghosting flag narrates what the engine actually observed (the real
    # silence window from the pending action's payload) — no dead buttons.
    assert "function _renderGhostRow(item)" in _TRACKER_JS
    assert "Gone quiet" in _TRACKER_JS
    assert "submission_age_days" in _TRACKER_JS


def test_tracker_attention_panel_hides_itself_on_failure_or_empty():
    # A bonus surface: it must never blank the primary tracker. Both the empty
    # and the failed fan-out collapse to a hidden panel.
    marker = "async function _loadAttention()"
    body = _TRACKER_JS[_TRACKER_JS.index(marker):]
    body = body[: body.index("async function _approveFollowUp")]
    assert body.count("panel.style.display = 'none'") >= 2
    # And concurrent loads (board load + campaign change) never let a SLOWER
    # earlier fan-out overwrite the panel with rows for a filter that is no
    # longer active: a monotonic seq is captured at entry and re-checked after
    # the awaits (alongside the campaign-id key) before the panel is touched.
    assert "let _attentionLoadSeq = 0;" in _TRACKER_JS
    assert "const seq = ++_attentionLoadSeq;" in body
    assert "if (seq !== _attentionLoadSeq) return;" in body
    assert "if (_attentionCampaignIds().join('|') !== campaignIds.join('|')) return;" in body


def test_tracker_attention_fanout_honors_the_shared_campaign_filter():
    # The panel fans out over the SAME shared campaign filter the board itself
    # renders through (_renderFiltered -> filterByCampaign) — never the raw
    # application list — so it can never show follow-ups/ghosting rows from a
    # search the board below is hiding.
    marker = "function _attentionCampaignIds()"
    body = _TRACKER_JS[_TRACKER_JS.index(marker):]
    body = body[: body.index("function _renderGhostRow")]
    assert "filterByCampaign(_lastApplications || [])" in body
    # And switching the shared campaign selection refreshes the panel under
    # the new lens (not just the board), so the two can never contradict.
    lmarker = "window.addEventListener('applicant-campaign-change'"
    listener = _TRACKER_JS[_TRACKER_JS.index(lmarker):]
    listener = listener[: listener.index("});") + 3]
    assert "_renderFiltered(host);" in listener
    assert "_loadAttention();" in listener


@pytest.mark.skipif(not _HAS_NODE, reason="node is required to execute the sliced JS")
def test_attention_fanout_filters_by_active_campaign_headlessly():
    # Slice the REAL shared filter (applicantCampaignSwitcher.filterByCampaign)
    # and the REAL fan-out (_attentionCampaignIds) out of the shipped sources
    # and run them together: with no selection every board campaign fans out;
    # with a campaign selected, only that campaign's id survives — the exact
    # lens _renderFiltered applies to the board below.
    switcher = (_JS / "applicantCampaignSwitcher.js").read_text(encoding="utf-8")
    f_start = switcher.index("export function filterByCampaign(items)")
    f_end = switcher.index("export async function loadCampaigns", f_start)
    filter_fn = switcher[f_start:f_end].replace("export function", "function", 1)
    a_start = _TRACKER_JS.index("function _attentionCampaignIds()")
    a_end = _TRACKER_JS.index("function _renderGhostRow", a_start)
    fanout_fn = _TRACKER_JS[a_start:a_end]
    script = f"""
let _active = '';
function _read() {{ return _active; }}
{filter_fn}
let _lastApplications = [
  {{ application_id: 'a-1', campaign_id: 'c1' }},
  {{ application_id: 'a-2', campaign_id: 'c2' }},
  {{ application_id: 'a-3', campaign_id: 'c1' }},
];
{fanout_fn}
const all = _attentionCampaignIds().sort();
_active = 'c1';
const filtered = _attentionCampaignIds();
console.log(JSON.stringify({{ all, filtered }}));
"""
    res = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=str(_REPO), capture_output=True, text=True, timeout=30,
    )
    assert res.returncode == 0, res.stderr
    out = json.loads(res.stdout.strip())
    assert out["all"] == ["c1", "c2"]
    assert out["filtered"] == ["c1"]


def test_followups_proxy_is_owner_gated_in_source():
    # DISC-15/DISC-15b: the followups proxy surfaces (read) and schedules
    # (write) the deployment owner's drafted follow-ups on a single-tenant
    # engine, so BOTH routes must gate with require_engine_owner, not plain
    # require_user (behavioral two-account coverage lives in
    # test_applicant_followups_routes.py).
    src = (_REPO / "routes" / "applicant_followups_routes.py").read_text(encoding="utf-8")
    assert "require_user" not in src.replace("require_engine_owner", "")
    read_block = src[src.index("async def attention"): src.index("@router.post")]
    assert "_require_owner(request)" in read_block
    write_block = src[src.index("async def approve_follow_up"):]
    assert "_require_owner(request)" in write_block


# ── 2. Activity: the learning loop's owner-scoped read + section ─────────────


def _make_activity_app(authed: bool = True) -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def _auth(request, call_next):
        request.state.current_user = "tester" if authed else None
        return await call_next(request)

    app.include_router(setup_applicant_activity_routes())
    return app


class FakeEngine:
    """Stands in for ApplicantEngineClient as an async context manager."""

    calls: list = []
    campaigns: list = []
    learning: dict = {}  # campaign_id -> engine learning payload
    raises: dict = {}    # key -> EngineError

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def list_campaigns(self):
        FakeEngine.calls.append("list_campaigns")
        if "list_campaigns" in FakeEngine.raises:
            raise FakeEngine.raises["list_campaigns"]
        return FakeEngine.campaigns

    async def admin_learning(self, cid):
        FakeEngine.calls.append(("admin_learning", cid))
        if ("admin_learning", cid) in FakeEngine.raises:
            raise FakeEngine.raises[("admin_learning", cid)]
        return FakeEngine.learning.get(cid, {})


@pytest.fixture(autouse=True)
def _reset_fake():
    FakeEngine.calls = []
    FakeEngine.campaigns = []
    FakeEngine.learning = {}
    FakeEngine.raises = {}
    yield


@pytest.fixture
def activity_client(monkeypatch):
    monkeypatch.setattr(activity_mod, "ApplicantEngineClient", FakeEngine)
    return TestClient(_make_activity_app())


def test_learning_requires_auth(monkeypatch):
    monkeypatch.setattr(activity_mod, "ApplicantEngineClient", FakeEngine)
    c = TestClient(_make_activity_app(authed=False))
    assert c.get("/api/applicant/activity/learning").status_code == 401


def test_learning_engine_offline_degrades_soft(activity_client):
    FakeEngine.raises["list_campaigns"] = EngineError("down", is_timeout=True)
    r = activity_client.get("/api/applicant/activity/learning")
    assert r.status_code == 200
    body = r.json()
    assert body["engine_available"] is False
    assert body["has_learning"] is False
    assert body["sources"] == []


def test_learning_no_campaign_yet_is_honestly_empty(activity_client):
    FakeEngine.campaigns = []
    r = activity_client.get("/api/applicant/activity/learning")
    assert r.status_code == 200
    body = r.json()
    assert body == {
        "engine_available": True,
        "has_learning": False,
        "summary": {},
        "sources": [],
        "converting_roles": [],
        "decline_reasons": [],
    }


def test_learning_success_forwards_the_engine_read_model(activity_client):
    FakeEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    FakeEngine.learning["c1"] = {
        "campaign_id": "c1",
        "summary": {"total_matched": 12, "total_approved": 5, "total_submitted": 3},
        "sources": [{"source": "linkedin", "matched": 12, "approved": 5, "submitted": 3,
                     "conversion_rate": 25.0}],
        "converting_roles": ["Backend Engineer"],
        "decline_reasons": [{"reason": "onsite", "count": 4}],
    }
    r = activity_client.get("/api/applicant/activity/learning")
    assert r.status_code == 200
    body = r.json()
    assert body["engine_available"] is True
    assert body["has_learning"] is True
    assert body["campaign_id"] == "c1"
    assert body["sources"][0]["source"] == "linkedin"
    assert body["converting_roles"] == ["Backend Engineer"]
    assert body["decline_reasons"] == [{"reason": "onsite", "count": 4}]
    assert ("admin_learning", "c1") in FakeEngine.calls


def test_learning_zero_volume_model_never_claims_learning(activity_client):
    # H-series honesty: an all-zero model must NOT light the section up.
    FakeEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    FakeEngine.learning["c1"] = {
        "summary": {"total_matched": 0, "total_approved": 0, "total_submitted": 0},
        "sources": [],
        "converting_roles": [],
        "decline_reasons": [],
    }
    r = activity_client.get("/api/applicant/activity/learning")
    assert r.status_code == 200
    assert r.json()["has_learning"] is False


def test_learning_malformed_summary_counters_degrade_soft(activity_client):
    # A malformed-but-200 engine payload (a non-numeric counter string) must
    # not escape the soft-degrade contract as a ValueError 500: the junk value
    # counts as 0 and has_learning is computed from the rest of the model.
    FakeEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    FakeEngine.learning["c1"] = {
        "summary": {"total_matched": "n/a", "total_approved": 0, "total_submitted": 3},
        "sources": [],
        "converting_roles": [],
        "decline_reasons": [],
    }
    r = activity_client.get("/api/applicant/activity/learning")
    assert r.status_code == 200
    body = r.json()
    assert body["engine_available"] is True
    assert body["has_learning"] is True  # total_submitted=3 still counts
    # And when EVERY signal is junk/empty, the section honestly stays dark.
    FakeEngine.learning["c1"]["summary"] = {"total_matched": "n/a"}
    FakeEngine.learning["c1"]["decline_reasons"] = []
    r = activity_client.get("/api/applicant/activity/learning")
    assert r.status_code == 200
    assert r.json()["has_learning"] is False


def test_learning_fetch_failure_degrades_soft(activity_client):
    FakeEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    FakeEngine.raises[("admin_learning", "c1")] = EngineError("boom", status=500)
    r = activity_client.get("/api/applicant/activity/learning")
    assert r.status_code == 200
    body = r.json()
    assert body["engine_available"] is True
    assert body["has_learning"] is False


def test_activity_page_wires_the_learning_section():
    # The Activity page owns the section: a dedicated host div, a loader over
    # the owner-scoped proxy, and honest gating on has_learning.
    assert 'id="applicant-activity-learning"' in _ACTIVITY_JS
    assert "_fetchJSON(`${API}/learning`)" in _ACTIVITY_JS
    assert "data.has_learning !== true" in _ACTIVITY_JS
    assert "What I’m learning" in _ACTIVITY_JS
    # Loaded on open AND on refresh, alongside the snapshot/runs it sits with.
    assert "_loadSnapshot(); _loadRuns(true); _loadLearning();" in _ACTIVITY_JS


@pytest.mark.skipif(not _HAS_NODE, reason="node is required to execute the sliced JS")
def test_learning_lines_builder_runs_headlessly():
    # Slice the pure exported builder out of the shipped source and run it for
    # real: real data narrates; empty/zero data yields NO lines (never a
    # fabricated learning claim).
    src = _ACTIVITY_JS
    start = src.index("export function _learningLines(data)")
    end = src.index("function _renderLearning", start)
    fn = src[start:end].replace("export function", "function", 1)
    script = fn + """
const rich = _learningLines({
  sources: [{ source: 'linkedin', matched: 12, approved: 5, submitted: 3 }],
  converting_roles: ['Backend Engineer'],
  decline_reasons: [{ reason: 'onsite', count: 4 }],
});
const empty = _learningLines({ sources: [], converting_roles: [], decline_reasons: [] });
console.log(JSON.stringify({ rich, empty }));
"""
    res = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=str(_REPO), capture_output=True, text=True, timeout=30,
    )
    assert res.returncode == 0, res.stderr
    out = json.loads(res.stdout.strip())
    assert out["empty"] == []
    assert len(out["rich"]) == 3
    assert "linkedin" in out["rich"][0]
    assert "3 of 12" in out["rich"][0]
    assert "Backend Engineer" in out["rich"][1]
    assert "onsite" in out["rich"][2]


# ── 3. Daily updates: the weekly recap read + line ───────────────────────────


def _mock_engine(handler):
    return ApplicantEngineClient(
        base_url="http://api:8000", transport=httpx.MockTransport(handler)
    )


@pytest.fixture
def make_email_client(monkeypatch):
    def _factory(handler, *, authed=True):
        monkeypatch.setattr(email_mod, "_engine_client", lambda: _mock_engine(handler))

        app = FastAPI()

        @app.middleware("http")
        async def _auth(request: Request, call_next):
            if authed:
                request.state.current_user = "kevin"
            return await call_next(request)

        app.include_router(setup_applicant_email_routes())
        return TestClient(app)

    return _factory


def test_weekly_recap_relays_to_the_engine(make_email_client):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["method"] = request.method
        return httpx.Response(200, json={
            "subject": "Your weekly recap",
            "body": "This week I sent 3 applications on your behalf.",
            "campaign_id": "camp-1",
            "applications_sent": 3,
            "best_source": "linkedin",
        })

    client = make_email_client(handler)
    resp = client.get("/api/applicant/email/digest/camp-1/weekly-recap")
    assert resp.status_code == 200
    assert captured == {"path": "/api/digest/camp-1/weekly-recap", "method": "GET"}
    assert resp.json()["applications_sent"] == 3


def test_weekly_recap_requires_auth(make_email_client):
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        return httpx.Response(200, json={})

    client = make_email_client(handler, authed=False)
    assert client.get("/api/applicant/email/digest/camp-1/weekly-recap").status_code == 401


def test_weekly_recap_forwards_the_engine_setup_gate(make_email_client):
    # A 409 setup gate is client-correctable — passed through, never masked.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"detail": "Finish setup first."})

    client = make_email_client(handler)
    resp = client.get("/api/applicant/email/digest/camp-1/weekly-recap")
    assert resp.status_code == 409


def test_weekly_recap_route_is_owner_gated_in_source():
    # DISC-15: the recap totals the deployment owner's real submission history,
    # so the route must gate with require_engine_owner, not plain require_user.
    src = (_REPO / "routes" / "applicant_email_routes.py").read_text(encoding="utf-8")
    start = src.index("async def get_weekly_recap")
    block = src[start: src.index("@router.post", start)]
    assert "require_engine_owner(request)" in block


def test_daily_updates_panel_renders_the_recap_line():
    # The panel fetches the recap alongside every digest load and renders the
    # engine's OWN first-person sentence (never recomposes the claim), hiding
    # the line entirely when there is nothing to show.
    assert 'id="applicant-digest-recap"' in _DIGEST_JS
    assert "/weekly-recap`" in _DIGEST_JS
    assert "Your week so far" in _DIGEST_JS
    assert "_loadWeeklyRecap(panel, campaignId);" in _DIGEST_JS
    # The engine-composed body is escaped, not rebuilt client-side.
    assert "${_esc(body)}" in _DIGEST_JS
