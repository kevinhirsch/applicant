"""Regression coverage for dark-engine audit item #56: posting metadata
(salary/location/work mode) inconsistently surfaced.

``salary``/``location``/``work_mode``/``source_key`` are captured per posting
(``src/applicant/core/entities/job_posting.py``), but before this change they
appeared only in the digest and the criteria editor. The Tracker's per-row
"View details" history disclosure (dark-engine audit #25,
``workspace/static/js/applicantTracker.js`` ``_renderHistoryBody``) already
rendered ``work_mode`` but omitted ``salary``/``location`` entirely, even
though a tracked application traces back to its originating posting.

``AdminQueryService.application_history`` now includes real ``salary``/
``location`` fields per row (see
``tests/unit/test_admin_query_posting_metadata.py`` for the engine-side
coverage). This file wires them through the ALREADY-BUILT "View details"
disclosure rather than a new endpoint:

  * ``workspace/routes/applicant_tracker_routes.py`` -- the existing
    ``GET /api/applicant/tracker/applications/{application_id}/history`` route
    already forwards the FULL per-application dict from the engine's
    ``tracker_application_history`` read (``{"found": True, **detail}``), so
    the new ``salary``/``location`` keys on that engine payload reach the
    front-door response unchanged. This test pins that passthrough
    specifically for ``salary``/``location`` (no route code changed for this
    task).
  * ``workspace/static/js/applicantTracker.js`` -- ``_renderHistoryBody`` now
    also renders "Location"/"Salary" lines from ``data.location``/
    ``data.salary``, using the same honest "Not recorded" convention already
    used for ``work_mode``.

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


@pytest.fixture(scope="module")
def node_available():
    if not _HAS_NODE:
        pytest.skip("node binary not on PATH")


# --- fake engine (mirrors test_applicant_tracker_history_detail.py) --------


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


def _history_row(app_id, *, salary=None, location=None, **extra):
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
        "salary": salary,
        "location": location,
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


def test_history_route_forwards_salary_and_location_untouched(tracker_client):
    _FakeHistoryEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    _FakeHistoryEngine.boards = {"c1": {"applications": [_tracker_row("a-1")]}}
    _FakeHistoryEngine.history_results = {
        "c1": {
            "campaign_id": "c1",
            "applications": [
                _history_row("a-1", salary="$150k-$180k", location="Remote (US)")
            ],
        }
    }

    r = tracker_client.get("/api/applicant/tracker/applications/a-1/history")

    assert r.status_code == 200
    body = r.json()
    assert body["salary"] == "$150k-$180k"
    assert body["location"] == "Remote (US)"


def test_history_route_salary_location_never_fabricated_when_absent(tracker_client):
    _FakeHistoryEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    _FakeHistoryEngine.boards = {"c1": {"applications": [_tracker_row("a-1")]}}
    _FakeHistoryEngine.history_results = {
        "c1": {"campaign_id": "c1", "applications": [_history_row("a-1")]}
    }

    r = tracker_client.get("/api/applicant/tracker/applications/a-1/history")

    assert r.status_code == 200
    body = r.json()
    assert body["salary"] is None
    assert body["location"] is None


def test_history_route_owner_isolation_still_applies_to_posting_metadata(tracker_client):
    # Mirrors the mandatory owner-isolation guard already covered for the rest
    # of the history payload -- salary/location don't bypass it.
    _FakeHistoryEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    _FakeHistoryEngine.boards = {"c1": {"applications": [_tracker_row("a-1")]}}
    _FakeHistoryEngine.history_results = {
        "c1": {
            "campaign_id": "c1",
            "applications": [
                _history_row("a-1", salary="$999k-secret-comp", location="Nowhere")
            ],
        }
    }

    r = tracker_client.get("/api/applicant/tracker/applications/not-mine/history")

    assert r.status_code == 404
    assert "$999k-secret-comp" not in r.text


# --- front-end: the "View details" disclosure now also renders it ----------


def test_render_history_body_reads_salary_and_location():
    src = _read(TRACKER_JS)
    fn = re.search(r"function _renderHistoryBody\(body, data\) \{.*?\n\}\n", src, re.S)
    assert fn, "expected a _renderHistoryBody(body, data) renderer"
    body = fn.group(0)
    assert "data.salary" in body
    assert "data.location" in body


def test_render_history_body_still_reads_work_mode():
    # This change must not regress the pre-existing work_mode rendering
    # (dark-engine audit #25).
    src = _read(TRACKER_JS)
    fn = re.search(r"function _renderHistoryBody\(body, data\) \{.*?\n\}\n", src, re.S)
    assert fn
    assert "data.work_mode" in fn.group(0)


def test_render_history_body_emits_salary_and_location_lines_in_the_output():
    src = _read(TRACKER_JS)
    fn = re.search(r"function _renderHistoryBody\(body, data\) \{.*?\n\}\n", src, re.S)
    assert fn
    body = fn.group(0)
    assert "Salary" in body
    assert "Location" in body


def test_render_history_body_uses_honest_not_recorded_fallback_for_new_fields():
    """Absent salary/location must render the same honest 'Not recorded'
    fallback already used for work mode -- never a fabricated value."""
    src = _read(TRACKER_JS)
    fn = re.search(r"function _renderHistoryBody\(body, data\) \{.*?\n\}\n", src, re.S)
    assert fn
    body = fn.group(0)
    assert body.count("Not recorded") >= 3


def test_render_history_body_escapes_salary_and_location():
    """salary/location must go through the shared esc() helper -- never raw
    string interpolation of engine-sourced data into innerHTML."""
    src = _read(TRACKER_JS)
    fn = re.search(r"function _renderHistoryBody\(body, data\) \{.*?\n\}\n", src, re.S)
    assert fn
    body = fn.group(0)
    assert "esc(data.salary" in body or re.search(r"salary\s*=\s*esc\(", body)
    assert "esc(data.location" in body or re.search(r"location\s*=\s*esc\(", body)


def test_history_section_has_no_fr_nfr_jargon_in_user_facing_copy():
    src = _read(TRACKER_JS)
    render_fn = re.search(r"function _renderHistoryBody\(body, data\) \{.*?\n\}\n", src, re.S)
    assert render_fn
    combined = render_fn.group(0)
    assert not re.search(r"\bFR-[A-Z]+-\d+\b", combined)
    assert not re.search(r"\bNFR-[A-Z]+-\d+\b", combined)


def test_node_check_applicant_tracker_js(node_available):
    res = subprocess.run(
        ["node", "--check", str(TRACKER_JS)],
        capture_output=True,
        timeout=15,
        text=True,
    )
    assert res.returncode == 0, f"node --check failed:\n{res.stderr}"
