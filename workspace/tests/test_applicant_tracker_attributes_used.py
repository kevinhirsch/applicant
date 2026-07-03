"""Regression coverage for dark-engine audit item #54: "which of your details
were used" on the Tracker.

The engine already stores the exact attribute map it consumed for each
application (``Application.attributes_used`` --
``src/applicant/core/entities/application.py``), and
``AdminQueryService.application_history`` now includes it in the per-application
row (see ``tests/unit/test_admin_query_attributes_used.py`` for the engine-side
coverage). This is a genuine privacy-trust artifact the engine already keeps
that no front-door surface showed.

This file wires it through the ALREADY-BUILT "View details" disclosure on the
Tracker board (dark-engine audit #25,
``workspace/static/js/applicantTracker.js`` / ``workspace/routes/
applicant_tracker_routes.py`` / ``workspace/src/applicant_engine.py``) rather
than a new endpoint:

  * ``workspace/routes/applicant_tracker_routes.py`` -- the existing
    ``GET /api/applicant/tracker/applications/{application_id}/history`` route
    already forwards the FULL per-application dict from the engine's
    ``tracker_application_history`` read (``{"found": True, **detail}``), so
    a new ``attributes_used`` key on that engine payload reaches the
    front-door response unchanged. This test pins that passthrough
    specifically for ``attributes_used`` (no route code changed for this
    task).
  * ``workspace/static/js/applicantTracker.js`` -- ``_renderHistoryBody`` now
    also renders a "Data used on this application" section from
    ``data.attributes_used``, via new ``_attributesUsedHTML`` /
    ``_prettyAttrLabel`` / ``_attrValueText`` helpers. Source-level shape is
    pinned below (same convention as
    ``test_applicant_tracker_history_detail_ui.py``: no DOM-independent entry
    point cheap enough to shim here for the browser-only module).

Per this series' standing DoD, each assertion below was verified, by hand, to
go RED when the corresponding piece of this task's change is reverted
(dropping ``attributes_used`` back out of the row dict, or reverting the JS
section), then confirmed GREEN again after restoring.
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
from routes.applicant_tracker_routes import setup_applicant_tracker_routes
from src.applicant_engine import EngineError

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


def _history_row(app_id, *, attributes_used=None, **extra):
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
        "attributes_used": attributes_used if attributes_used is not None else {},
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
    app.include_router(setup_applicant_tracker_routes())
    return app


@pytest.fixture
def tracker_client(monkeypatch):
    monkeypatch.setattr(tracker_routes, "ApplicantEngineClient", _FakeHistoryEngine)
    return TestClient(_make_tracker_app())


# --- route passthrough (real data, no new endpoint) -------------------------


def test_history_route_forwards_attributes_used_untouched(tracker_client):
    _FakeHistoryEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    _FakeHistoryEngine.boards = {"c1": {"applications": [_tracker_row("a-1")]}}
    _FakeHistoryEngine.history_results = {
        "c1": {
            "campaign_id": "c1",
            "applications": [
                _history_row(
                    "a-1",
                    attributes_used={"First Name": "Kevin", "email": "k@example.com"},
                )
            ],
        }
    }

    r = tracker_client.get("/api/applicant/tracker/applications/a-1/history")

    assert r.status_code == 200
    body = r.json()
    assert body["attributes_used"] == {"First Name": "Kevin", "email": "k@example.com"}


def test_history_route_attributes_used_never_fabricated_when_empty(tracker_client):
    _FakeHistoryEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    _FakeHistoryEngine.boards = {"c1": {"applications": [_tracker_row("a-1")]}}
    _FakeHistoryEngine.history_results = {
        "c1": {"campaign_id": "c1", "applications": [_history_row("a-1")]}
    }

    r = tracker_client.get("/api/applicant/tracker/applications/a-1/history")

    assert r.status_code == 200
    assert r.json()["attributes_used"] == {}


def test_history_route_owner_isolation_still_applies(tracker_client):
    # Mirrors the mandatory owner-isolation guard already covered for the rest
    # of the history payload -- attributes_used doesn't bypass it.
    _FakeHistoryEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    _FakeHistoryEngine.boards = {"c1": {"applications": [_tracker_row("a-1")]}}
    _FakeHistoryEngine.history_results = {
        "c1": {
            "campaign_id": "c1",
            "applications": [_history_row("a-1", attributes_used={"ssn": "should-never-leak"})],
        }
    }

    r = tracker_client.get("/api/applicant/tracker/applications/not-mine/history")

    assert r.status_code == 404
    assert "should-never-leak" not in r.text


# --- front-end: the "View details" disclosure now also renders it ----------


def test_render_history_body_calls_the_attributes_used_renderer():
    src = _read(TRACKER_JS)
    fn = re.search(r"function _renderHistoryBody\(body, data\) \{.*?\n\}\n", src, re.S)
    assert fn, "expected a _renderHistoryBody(body, data) renderer"
    body = fn.group(0)
    assert "data.attributes_used" in body
    assert "_attributesUsedHTML(" in body


def test_attributes_used_renderer_exists_and_handles_the_empty_case():
    src = _read(TRACKER_JS)
    fn = re.search(r"function _attributesUsedHTML\(attributesUsed\) \{.*?\n\}\n", src, re.S)
    assert fn, "expected an _attributesUsedHTML(attributesUsed) renderer"
    body = fn.group(0)
    # Real-data-only: an application with nothing recorded gets an honest
    # empty-state message, never a fabricated placeholder list.
    assert "No details recorded" in body


def test_attributes_used_renderer_escapes_keys_and_values():
    src = _read(TRACKER_JS)
    fn = re.search(r"function _attributesUsedHTML\(attributesUsed\) \{.*?\n\}\n", src, re.S)
    assert fn
    body = fn.group(0)
    # Both the plain-language label AND the value must go through esc() --
    # never raw string interpolation of engine-sourced data into innerHTML.
    assert body.count("esc(") >= 2


def test_pretty_attr_label_helper_exists_for_plain_language_names():
    """Attribute names render as plain language (Title Case), not the raw
    storage key, per the white-label/plain-language requirement."""
    src = _read(TRACKER_JS)
    fn = re.search(r"function _prettyAttrLabel\(key\) \{.*?\n\}\n", src, re.S)
    assert fn, "expected a _prettyAttrLabel(key) helper"


def test_attributes_used_section_has_no_fr_nfr_jargon_in_user_facing_copy():
    src = _read(TRACKER_JS)
    fn = re.search(r"function _attributesUsedHTML\(attributesUsed\) \{.*?\n\}\n", src, re.S)
    render_fn = re.search(r"function _renderHistoryBody\(body, data\) \{.*?\n\}\n", src, re.S)
    assert fn and render_fn
    combined = fn.group(0) + render_fn.group(0)
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
