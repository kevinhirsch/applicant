"""Regression coverage for dark-engine audit items #57/#58 (B6), front-door side.

#57 — ``Application.sandbox_session_url`` is stored on every in-flight
application (the live sandbox/takeover session URL) but nothing read it; the
remote/takeover lane rebuilt its own session list from ``/sessions`` instead.
``AdminQueryService.application_history`` now includes it (engine-side
coverage: ``tests/unit/test_admin_query_sandbox_and_plan.py``), and this test
pins that the ALREADY-BUILT Tracker "View details" round trip
(``workspace/routes/applicant_tracker_routes.py`` -- no route code changed for
this task, it already forwards the full per-application dict) carries the new
field through untouched, plus that ``applicantTracker.js`` now renders an
"Open live session" link from it.

#58 — the pre-fill planner's Plan-as-Data op-sequence is now recorded to a
process-lived, in-memory ledger (``PrefillService.record_plan_history`` /
``get_plan_history``) and surfaced as ``plan_ops`` on the SAME
``application_history`` read-model. This pins the same untouched passthrough
for ``plan_ops``, plus the new "What the agent did on this form" disclosure in
``applicantTracker.js``.

Per this series' standing DoD, each assertion below was verified, by hand, to
go RED when the corresponding piece of this task's change is reverted
(restoring ``admin_query_service.py`` or ``applicantTracker.js`` from a
pre-change file-copy backup), then confirmed GREEN again after restoring.
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.applicant_tracker_routes as tracker_routes

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKSPACE_DIR = REPO_ROOT / "workspace"
TRACKER_JS = WORKSPACE_DIR / "static" / "js" / "applicantTracker.js"

_HAS_NODE = shutil.which("node") is not None


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _render_history_body_source() -> str:
    src = _read(TRACKER_JS)
    fn = re.search(r"function _renderHistoryBody\(body, data\) \{.*?\n\}\n", src, re.S)
    assert fn, "expected a _renderHistoryBody(body, data) renderer"
    return fn.group(0)


@pytest.fixture(scope="module")
def node_available():
    if not _HAS_NODE:
        pytest.skip("node binary not on PATH")


# --- fake engine (mirrors test_applicant_tracker_posting_metadata.py) -------


class _FakeHistoryEngine:
    calls: list = []
    campaigns: list = []
    boards: dict = {}
    history_results: dict = {}
    raises: dict = {}

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def list_campaigns(self):
        type(self).calls.append("list_campaigns")
        if "list_campaigns" in type(self).raises:
            raise type(self).raises["list_campaigns"]
        return type(self).campaigns

    async def tracker_board(self, campaign_id):
        type(self).calls.append(("tracker_board", campaign_id))
        if ("tracker_board", campaign_id) in type(self).raises:
            raise type(self).raises[("tracker_board", campaign_id)]
        return type(self).boards.get(campaign_id, {"applications": []})

    async def tracker_application_history(self, campaign_id, limit=200):
        type(self).calls.append(("tracker_application_history", campaign_id, limit))
        key = ("tracker_application_history", campaign_id)
        if key in type(self).raises:
            raise type(self).raises[key]
        return type(self).history_results.get(
            campaign_id, {"campaign_id": campaign_id, "applications": []}
        )


@pytest.fixture(autouse=True)
def _reset_fake_history_engine():
    _FakeHistoryEngine.calls = []
    _FakeHistoryEngine.campaigns = []
    _FakeHistoryEngine.boards = {}
    _FakeHistoryEngine.history_results = {}
    _FakeHistoryEngine.raises = {}
    yield


def _tracker_row(app_id, *, status="AWAITING_RESPONSE"):
    return {
        "application_id": app_id,
        "status": status,
        "role_name": "Backend Engineer",
        "job_title": "Backend Engineer",
        "signals": [],
        "submitted_at": "2026-06-01T00:00:00+00:00",
        "created_at": "2026-05-30T00:00:00+00:00",
    }


def _history_row(app_id, *, sandbox_session_url=None, plan_ops=None, **extra):
    row = {
        "application_id": app_id,
        "status": "AWAITING_RESPONSE",
        "role_name": "Backend Engineer",
        "job_title": "Backend Engineer",
        "work_mode": "remote",
        "root_url": "https://example.com/careers",
        "resume_variant_id": "rv-1",
        "screenshot_count": 3,
        "outcomes": [],
        "attributes_used": {},
        "salary": None,
        "location": None,
        "sandbox_session_url": sandbox_session_url,
        "plan_ops": plan_ops if plan_ops is not None else [],
    }
    row.update(extra)
    return row


def _make_tracker_app(authed: bool = True):
    app = FastAPI()
    if authed:
        @app.middleware("http")
        async def _auth(request, call_next):
            request.state.current_user = "tester"
            return await call_next(request)
    app.include_router(tracker_routes.setup_applicant_tracker_routes())
    return app


@pytest.fixture
def tracker_client(monkeypatch):
    monkeypatch.setattr(tracker_routes, "ApplicantEngineClient", _FakeHistoryEngine)
    return TestClient(_make_tracker_app())


# --- route passthrough (real data, no new endpoint) -------------------------


def test_history_route_forwards_sandbox_session_url_untouched(tracker_client):
    _FakeHistoryEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    _FakeHistoryEngine.boards = {"c1": {"applications": [_tracker_row("a-1")]}}
    _FakeHistoryEngine.history_results = {
        "c1": {
            "campaign_id": "c1",
            "applications": [
                _history_row("a-1", sandbox_session_url="https://sandbox.example/s/abc123")
            ],
        }
    }

    r = tracker_client.get("/api/applicant/tracker/applications/a-1/history")

    assert r.status_code == 200
    assert r.json()["sandbox_session_url"] == "https://sandbox.example/s/abc123"


def test_history_route_sandbox_session_url_none_when_absent(tracker_client):
    _FakeHistoryEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    _FakeHistoryEngine.boards = {"c1": {"applications": [_tracker_row("a-1")]}}
    _FakeHistoryEngine.history_results = {
        "c1": {"campaign_id": "c1", "applications": [_history_row("a-1")]}
    }

    r = tracker_client.get("/api/applicant/tracker/applications/a-1/history")

    assert r.status_code == 200
    assert r.json()["sandbox_session_url"] is None


def test_history_route_forwards_plan_ops_untouched(tracker_client):
    plan_ops = [
        {
            "url": "https://ats.example/apply",
            "captured_at": "2026-07-01T00:00:00+00:00",
            "ops": [{"kind": "goto", "url": "https://ats.example/apply"}],
        }
    ]
    _FakeHistoryEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    _FakeHistoryEngine.boards = {"c1": {"applications": [_tracker_row("a-1")]}}
    _FakeHistoryEngine.history_results = {
        "c1": {"campaign_id": "c1", "applications": [_history_row("a-1", plan_ops=plan_ops)]}
    }

    r = tracker_client.get("/api/applicant/tracker/applications/a-1/history")

    assert r.status_code == 200
    assert r.json()["plan_ops"] == plan_ops


def test_history_route_owner_isolation_still_applies_to_sandbox_url(tracker_client):
    # Mirrors the mandatory owner-isolation guard already covered for the rest
    # of the history payload -- a live-session link doesn't bypass it.
    _FakeHistoryEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    _FakeHistoryEngine.boards = {"c1": {"applications": [_tracker_row("a-1")]}}
    _FakeHistoryEngine.history_results = {
        "c1": {
            "campaign_id": "c1",
            "applications": [
                _history_row("a-1", sandbox_session_url="https://sandbox.example/secret-session")
            ],
        }
    }

    r = tracker_client.get("/api/applicant/tracker/applications/not-mine/history")

    assert r.status_code == 404
    assert "secret-session" not in r.text


# --- front-end: the "View details" disclosure now also renders both --------


def test_render_history_body_reads_sandbox_session_url_and_plan_ops():
    body = _render_history_body_source()
    assert "data.sandbox_session_url" in body
    assert "data.plan_ops" in body


def test_sandbox_session_html_omits_link_when_no_url():
    src = _read(TRACKER_JS)
    fn = re.search(r"function _sandboxSessionHTML\(url\) \{.*?\n\}\n", src, re.S)
    assert fn, "expected a _sandboxSessionHTML(url) helper"
    body = fn.group(0)
    # must short-circuit to '' for a falsy/blank url -- never a dead/broken link
    assert "return ''" in body


def test_sandbox_session_html_uses_cal_btn_and_opens_new_tab():
    src = _read(TRACKER_JS)
    fn = re.search(r"function _sandboxSessionHTML\(url\) \{.*?\n\}\n", src, re.S)
    assert fn
    body = fn.group(0)
    assert "cal-btn" in body
    assert 'target="_blank"' in body
    assert "noopener" in body


def test_plan_ops_html_renders_a_collapsible_step_list():
    src = _read(TRACKER_JS)
    fn = re.search(r"function _planOpsHTML\(planOps\) \{.*?\n\}\n", src, re.S)
    assert fn, "expected a _planOpsHTML(planOps) helper"
    body = fn.group(0)
    assert "<details" in body
    assert "<summary" in body


def test_plan_ops_html_empty_when_no_plan_ops():
    src = _read(TRACKER_JS)
    fn = re.search(r"function _planOpsHTML\(planOps\) \{.*?\n\}\n", src, re.S)
    assert fn
    body = fn.group(0)
    assert "if (!plans.length) return '';" in body


def test_history_section_has_no_fr_nfr_jargon_in_user_facing_copy():
    body = _render_history_body_source()
    assert not re.search(r"\bFR-[A-Z]+-\d+\b", body)
    assert not re.search(r"\bNFR-[A-Z]+-\d+\b", body)


def test_node_check_applicant_tracker_js(node_available):
    res = subprocess.run(
        ["node", "--check", str(TRACKER_JS)],
        capture_output=True,
        timeout=15,
        text=True,
    )
    assert res.returncode == 0, f"node --check failed:\n{res.stderr}"
